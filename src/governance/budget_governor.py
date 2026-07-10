"""
Budget Governor -- live facade over budget sources + priority-aware pressure.

Sources (no invented costs):
  1. config/budget.yaml + env + GovernorConfig defaults (via config_loader)
  2. research paid-call cap -- RESEARCH_MAX_PAID_PER_DAY + logs/research_budget.jsonl
  3. priority_manager weights -- scale soft/escalate only (hard ceiling never rises)

Live call path: cost_governor.govern() invokes check_estimated_usd() so plan
verdicts reflect budget pressure and project priority. govern_plan() still
delegates full furnace logic to cost_governor (single plan policy).

Hard ceiling always BLOCKs regardless of priority or trust.
High-priority projects (weight >= threshold) are protected from *soft-budget*
DOWNGRADE only — they still ESCALATE/BLOCK on escalate/hard thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class BudgetVerdict(str, Enum):
    ALLOW = "allow"
    DOWNGRADE = "downgrade"   # over soft budget -- prefer cheaper plan
    ESCALATE = "escalate"     # over escalate budget -- human must approve
    BLOCK = "block"           # over hard ceiling -- refuse


@dataclass(frozen=True)
class BudgetThresholds:
    soft_budget: float
    escalate_budget: float
    hard_ceiling: float
    research_max_paid_per_day: int

    def to_entry(self) -> dict:
        return {
            "soft_budget": self.soft_budget,
            "escalate_budget": self.escalate_budget,
            "hard_ceiling": self.hard_ceiling,
            "research_max_paid_per_day": self.research_max_paid_per_day,
        }


@dataclass(frozen=True)
class BudgetStatus:
    thresholds: BudgetThresholds
    research_paid_today: int
    research_remaining: int
    research_capped: bool

    def to_entry(self) -> dict:
        return {
            **self.thresholds.to_entry(),
            "research_paid_today": self.research_paid_today,
            "research_remaining": self.research_remaining,
            "research_capped": self.research_capped,
        }


@dataclass(frozen=True)
class BudgetDecision:
    verdict: BudgetVerdict
    estimated_usd: float
    reasons: list[str]
    trust_level: str
    priority_weight: float = 0.5
    effective_soft: float = 2.0
    effective_escalate: float = 5.0

    def to_entry(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "estimated_usd": self.estimated_usd,
            "reasons": list(self.reasons),
            "trust_level": self.trust_level,
            "priority_weight": self.priority_weight,
            "effective_soft": self.effective_soft,
            "effective_escalate": self.effective_escalate,
        }


def _thresholds() -> BudgetThresholds:
    from src.governance.config_loader import load_budget_config
    cfg = load_budget_config()
    return BudgetThresholds(
        soft_budget=float(cfg["soft_budget"]),
        escalate_budget=float(cfg["escalate_budget"]),
        hard_ceiling=float(cfg["hard_ceiling"]),
        research_max_paid_per_day=int(cfg["research_max_paid_per_day"]),
    )


def research_paid_today() -> int:
    """Live paid-research call count for today (from research layer)."""
    try:
        from src.execution.research import paid_calls_today
        return int(paid_calls_today())
    except Exception:
        return 0


def status() -> BudgetStatus:
    thr = _thresholds()
    used = research_paid_today()
    remaining = max(0, thr.research_max_paid_per_day - used)
    return BudgetStatus(
        thresholds=thr,
        research_paid_today=used,
        research_remaining=remaining,
        research_capped=used >= thr.research_max_paid_per_day,
    )


def allow_paid_research() -> bool:
    """True iff another paid research call is within the daily cap."""
    return not status().research_capped


def check_estimated_usd(
    estimated_usd: float,
    trust_level: str = "UNTRUSTED",
    *,
    project: str | None = None,
    priority_weight: float | None = None,
    soft_budget: float | None = None,
    escalate_budget: float | None = None,
    hard_ceiling: float | None = None,
) -> BudgetDecision:
    """Apply priority-scaled soft/escalate thresholds to an estimated-USD figure.

    Hard ceiling is never increased by priority. Trust=AUTONOMOUS may
    auto-clear an over-escalate figure (same rule as cost_governor). High
    priority projects skip soft-budget DOWNGRADE (protected) but not escalate.

    Optional soft_budget / escalate_budget / hard_ceiling override the loaded
    defaults (used when cost_governor passes a GovernorConfig).
    """
    from src.governance.priority_manager import (
        weight_for, budget_scale, is_high_priority,
    )

    thr = _thresholds()
    base_soft = float(soft_budget) if soft_budget is not None else thr.soft_budget
    base_esc = float(escalate_budget) if escalate_budget is not None else thr.escalate_budget
    hard = float(hard_ceiling) if hard_ceiling is not None else thr.hard_ceiling
    cost = float(estimated_usd)
    tl = (trust_level or "UNTRUSTED").upper()
    w = float(priority_weight) if priority_weight is not None else weight_for(project)
    scale = budget_scale(w)
    soft = base_soft * scale
    escalate = base_esc * scale
    # hard never scaled up
    reasons: list[str] = []

    if cost > hard:
        reasons.append(
            f"Estimated ${cost:.2f} exceeds hard ceiling ${hard:.2f}."
        )
        return BudgetDecision(
            BudgetVerdict.BLOCK, cost, reasons, tl, w, soft, escalate,
        )

    if cost > escalate:
        reasons.append(
            f"Estimated ${cost:.2f} exceeds escalate budget ${escalate:.2f} "
            f"(base ${base_esc:.2f} × priority_scale {scale:.2f})."
        )
        if tl == "AUTONOMOUS":
            reasons.append("Trust=AUTONOMOUS -> auto-approved despite cost.")
            return BudgetDecision(
                BudgetVerdict.ALLOW, cost, reasons, tl, w, soft, escalate,
            )
        return BudgetDecision(
            BudgetVerdict.ESCALATE, cost, reasons, tl, w, soft, escalate,
        )

    if cost > soft:
        if is_high_priority(project) or w >= 0.75:
            reasons.append(
                f"Estimated ${cost:.2f} over soft ${soft:.2f}, but high priority "
                f"(weight={w:.2f}) protected from soft-budget downgrade."
            )
            return BudgetDecision(
                BudgetVerdict.ALLOW, cost, reasons, tl, w, soft, escalate,
            )
        reasons.append(
            f"Estimated ${cost:.2f} over soft budget ${soft:.2f} "
            f"(base ${base_soft:.2f} × priority_scale {scale:.2f})."
        )
        return BudgetDecision(
            BudgetVerdict.DOWNGRADE, cost, reasons, tl, w, soft, escalate,
        )

    reasons.append(
        f"Within budget at ${cost:.2f} (soft ${soft:.2f}, priority weight {w:.2f})."
    )
    return BudgetDecision(
        BudgetVerdict.ALLOW, cost, reasons, tl, w, soft, escalate,
    )


def govern_plan(plan: Any, trust_level: str = "UNTRUSTED", project: str | None = None) -> Any:
    """Delegate full WorkflowPlan governance to cost_governor (single policy)."""
    from src.workflow.cost_governor import govern, GovernorConfig
    return govern(plan, GovernorConfig(trust_level=trust_level.upper()), project=project)


if __name__ == "__main__":
    s = status()
    print("thresholds:", s.thresholds.to_entry())
    print("research paid today:", s.research_paid_today, "remaining:", s.research_remaining)
    for usd in (0.5, 3.0, 8.0, 30.0):
        d = check_estimated_usd(usd, "UNTRUSTED")
        print(f"  ${usd:.2f} -> {d.verdict.value}: {d.reasons[0]}")
