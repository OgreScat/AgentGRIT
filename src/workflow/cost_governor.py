"""
GRIT Cost Governor

The policy gate that sits between "Claude wants to run a workflow" and "1,000
agents actually spawn." This is the answer to the question Anthropic's runtime
never asks: *is this run worth it, and can it be cheaper without losing the
parts that matter?*

Responsibilities:
  1. Normalize a WorkflowPlan into sane execution order.
  2. Estimate spend and compare against budget + remaining quota.
  3. Produce a DOWNGRADED counter-plan that preserves hard stages but cheapens
     soft ones, and quantify the savings.
  4. Run the bylaw check on the PLAN (not just individual commands): block
     furnace runs that aren't justified, escalate borderline ones, allow the
     rest.
  5. Emit an approval payload suitable for Telegram (mobile sign-off).

It deliberately does NOT execute anything. GRIT's honest seams are PRE-RUN
(this) and POST-RUN (verification.py). The runtime itself is closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .planner import (
    WorkflowPlan, PlannedStage, StageKind, StageModel,
    HARD_KINDS, MODEL_COST_PER_1K, plan_workflow,
)


# Canonical execution order regardless of detection order.
_EXEC_ORDER = [
    StageKind.RESEARCH,
    StageKind.CLASSIFY,
    StageKind.ARCHITECTURE,
    StageKind.CODE_GEN,
    StageKind.REFACTOR,
    StageKind.MIGRATION,
    StageKind.TEST,
    StageKind.SECURITY,
    StageKind.REVIEW,
    StageKind.ADVERSARIAL,
    StageKind.SUMMARIZE,
    StageKind.FORMAT,
    StageKind.EXPLAIN,
]


class Verdict(str, Enum):
    ALLOW = "allow"        # within budget, no concerns — auto-runnable
    DOWNGRADE = "downgrade"  # runnable, but a cheaper plan is offered first
    ESCALATE = "escalate"  # needs human sign-off (cost or risk)
    BLOCK = "block"        # refuse: furnace with no justification / over hard ceiling


@dataclass
class GovernorConfig:
    soft_budget: float = 2.00      # above this → DOWNGRADE offered
    escalate_budget: float = 5.00  # above this → ESCALATE (human must approve)
    hard_ceiling: float = 25.00    # above this → BLOCK outright
    furnace_agent_threshold: int = 40  # total agents that counts as a furnace
    trust_level: str = "UNTRUSTED"  # UNTRUSTED | TRUSTED | AUTONOMOUS


@dataclass
class GovernedDecision:
    verdict: Verdict
    plan: WorkflowPlan
    downgraded_plan: WorkflowPlan | None
    reasons: list[str] = field(default_factory=list)
    savings: float = 0.0

    def telegram_payload(self) -> dict:
        """Compact structure for the bot to render with approve/reject buttons."""
        chosen = self.downgraded_plan or self.plan
        return {
            "verdict": self.verdict.value,
            "task": self.plan.task,
            "cost": chosen.governed_cost,
            "naive_opus_cost": self.plan.naive_opus_cost,
            "savings_vs_default": round(self.plan.naive_opus_cost - chosen.governed_cost, 2),
            "savings_vs_governed": round(self.savings, 2),
            "stages": [
                {"name": s.name, "model": s.assigned_model.value, "agents": s.fanout}
                for s in chosen.stages
            ],
            "reasons": self.reasons,
            "needs_human": self.verdict in (Verdict.ESCALATE, Verdict.BLOCK),
            "routing_spec": chosen.routing_spec(),
        }


def _normalize_order(plan: WorkflowPlan) -> WorkflowPlan:
    rank = {k: i for i, k in enumerate(_EXEC_ORDER)}
    plan.stages.sort(key=lambda s: rank.get(s.kind, 99))
    return plan


def _downgrade(plan: WorkflowPlan) -> tuple[WorkflowPlan, float]:
    """
    Build a cheaper counter-plan: every soft stage that has a cheaper_alternative
    is dropped to it. Hard stages are untouched. Returns (new_plan, savings).
    """
    new_stages: list[PlannedStage] = []
    saved = 0.0
    for s in plan.stages:
        if s.kind not in HARD_KINDS and s.cheaper_alternative is not None:
            new_cost = (s.est_tokens / 1000) * MODEL_COST_PER_1K[s.cheaper_alternative]
            saved += (s.est_cost - new_cost)
            new_stages.append(PlannedStage(
                name=s.name,
                kind=s.kind,
                assigned_model=s.cheaper_alternative,
                rationale=s.rationale + " [downgraded by governor]",
                fanout=s.fanout,
                est_tokens=s.est_tokens,
                est_cost=round(new_cost, 4),
                cheaper_alternative=None,
                cheaper_cost=None,
            ))
        else:
            new_stages.append(s)

    governed = round(sum(s.est_cost for s in new_stages), 2)
    new_plan = WorkflowPlan(
        task=plan.task,
        stages=new_stages,
        total_tokens=plan.total_tokens,
        total_cost=governed,
        governed_cost=governed,
        naive_opus_cost=plan.naive_opus_cost,
        warnings=list(plan.warnings),
    )
    return new_plan, round(saved, 2)


def _maybe_record(plan: WorkflowPlan, decision: GovernedDecision, cfg: GovernorConfig) -> None:
    """Append a decision record for BLOCK/ESCALATE only (high-signal). Fail-safe."""
    if decision.verdict not in (Verdict.BLOCK, Verdict.ESCALATE):
        return
    # Do not pollute production logs/ during unit tests (pytest sets this env).
    import os
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    try:
        from src.governance.decision_record import record
        from src.governance.bylaws import BylawResult, BylawAction

        bylaw_action = (
            BylawAction.BLOCK if decision.verdict is Verdict.BLOCK
            else BylawAction.ESCALATE
        )
        reason = "; ".join(decision.reasons) or decision.verdict.value
        # Minimal routing stand-in: provider unknown at plan stage; cost is real.
        class _Route:
            provider = None
            category = None
            confidence = None
            estimated_cost = plan.governed_cost
            reason = f"workflow plan cost ${plan.governed_cost:.2f}"

        record(
            action=plan.task[:200],
            routing=_Route(),
            bylaw=BylawResult(action=bylaw_action, reason=reason),
            authorized_by=f"cost_governor:trust={cfg.trust_level}",
        )
    except Exception:
        pass


def govern(plan: WorkflowPlan, config: GovernorConfig | None = None) -> GovernedDecision:
    cfg = config or GovernorConfig()
    plan = _normalize_order(plan)
    reasons: list[str] = []

    total_agents = sum(s.fanout for s in plan.stages)
    opus_agents = sum(s.fanout for s in plan.stages
                      if s.assigned_model == StageModel.OPUS)
    cost = plan.governed_cost

    # Always compute the downgrade so we can show savings even on ALLOW.
    downgraded, savings = _downgrade(plan)
    has_downgrade = savings > 0.005

    def _done(verdict: Verdict, plan_out: WorkflowPlan, down, reas, sav) -> GovernedDecision:
        d = GovernedDecision(verdict, plan_out, down, reas, sav)
        _maybe_record(plan_out, d, cfg)
        return d

    # 1. Hard ceiling → BLOCK.
    if cost > cfg.hard_ceiling:
        reasons.append(
            f"Estimated ${cost:.2f} exceeds hard ceiling ${cfg.hard_ceiling:.2f}. "
            f"Scope to a slice and re-plan."
        )
        return _done(Verdict.BLOCK, plan, downgraded if has_downgrade else None,
                     reasons, savings)

    # 2. Unjustified furnace → BLOCK. Many agents, but none on hard kinds.
    justified = any(s.kind in HARD_KINDS for s in plan.stages)
    if total_agents >= cfg.furnace_agent_threshold and not justified:
        reasons.append(
            f"{total_agents} agents planned with no genuinely-hard stage to justify "
            f"the spend. This is a furnace. Re-scope or split into smaller runs."
        )
        return _done(Verdict.BLOCK, plan, downgraded if has_downgrade else None,
                     reasons, savings)

    # 3. Over escalate budget → ESCALATE (unless AUTONOMOUS trust).
    if cost > cfg.escalate_budget:
        reasons.append(
            f"Estimated ${cost:.2f} exceeds escalate budget ${cfg.escalate_budget:.2f}."
        )
        if opus_agents:
            reasons.append(f"{opus_agents} Opus agents in plan.")
        if has_downgrade:
            reasons.append(
                f"A governed downgrade saves ${savings:.2f} "
                f"(→ ${downgraded.governed_cost:.2f}) without touching hard stages."
            )
        if cfg.trust_level == "AUTONOMOUS":
            reasons.append("Trust=AUTONOMOUS → auto-approved despite cost.")
            return _done(Verdict.DOWNGRADE if has_downgrade else Verdict.ALLOW,
                         plan, downgraded if has_downgrade else None,
                         reasons, savings)
        return _done(Verdict.ESCALATE, plan,
                     downgraded if has_downgrade else None, reasons, savings)

    # 4. Over soft budget but under escalate → DOWNGRADE offer.
    if cost > cfg.soft_budget and has_downgrade:
        reasons.append(
            f"Estimated ${cost:.2f} over soft budget ${cfg.soft_budget:.2f}. "
            f"Offered downgrade → ${downgraded.governed_cost:.2f} (saves ${savings:.2f})."
        )
        return _done(Verdict.DOWNGRADE, plan, downgraded, reasons, savings)

    # 5. Otherwise ALLOW. Still surface a downgrade if it's meaningfully cheaper.
    if has_downgrade:
        reasons.append(
            f"Within budget. Optional downgrade available (saves ${savings:.2f})."
        )
        return _done(Verdict.ALLOW, plan, downgraded, reasons, savings)

    reasons.append(f"Within budget at ${cost:.2f}. No concerns.")
    return _done(Verdict.ALLOW, plan, None, reasons, savings)


def govern_task(task: str, config: GovernorConfig | None = None) -> GovernedDecision:
    """Convenience: plan + govern in one call."""
    cfg = config or GovernorConfig()
    plan = plan_workflow(task, budget_ceiling=cfg.escalate_budget)
    return govern(plan, cfg)


# ── CLI demo ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cases = [
        ("Format this file and add docstrings", GovernorConfig()),
        ("Research the top 10 DeFi protocols by TVL and cross-check their security audits",
         GovernorConfig()),
        ("Port our 500-file Python service from Flask to FastAPI and keep tests passing",
         GovernorConfig()),
        ("Port our 500-file Python service from Flask to FastAPI and keep tests passing",
         GovernorConfig(trust_level="AUTONOMOUS")),
    ]
    for task, cfg in cases:
        d = govern_task(task, cfg)
        print("=" * 70)
        print(f"TASK: {task}")
        print(f"TRUST: {cfg.trust_level}")
        print(f"VERDICT: {d.verdict.value.upper()}")
        for r in d.reasons:
            print(f"  • {r}")
        chosen = d.downgraded_plan or d.plan
        print(f"  Plan cost: ${chosen.governed_cost:.2f}  "
              f"(all-Opus would be ${d.plan.naive_opus_cost:.2f})")
        print()
