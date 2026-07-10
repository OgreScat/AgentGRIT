"""
GRIT Workflow Planner

Re-positioned role: GRIT no longer orchestrates agents itself (Dynamic Workflows
does that natively now). Instead, GRIT plans HOW a workflow should be staged and
WHICH model each stage should use, so the expensive native runtime doesn't default
every one of up to 1,000 subagents to your session model.

This module takes a task description and produces a cost-annotated stage plan:
- Decompose the task into ordered stages
- Classify each stage (reusing the 2-stage router's signal scoring)
- Assign each stage the cheapest CAPABLE model (via capability map)
- Estimate token/dollar cost, with a cheaper alternative plan
- Emit both a human-readable plan (for Telegram approval) and a JSON routing
  spec you can hand to Claude when describing the workflow.

Integration seam (documented, shipping):
  Claude Code docs: "Every agent in a workflow uses your session's model unless
  the script routes a stage to a different one... Ask Claude to use a smaller
  model for stages that don't need the strongest one."
  We systematize that ad-hoc suggestion into a policy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum


# ── Model tiers (cost-ordered) ────────────────────────────────────────────────
# Kept local to this module so the planner is import-light and testable on its
# own; mirrors Provider costs in router_v2 but expressed per-stage.

class StageModel(str, Enum):
    OLLAMA = "ollama"            # local, ~free, weak at orchestration/tool use
    PERPLEXITY = "perplexity"   # cheap, web search built in, no tool exec
    HAIKU = "claude-haiku"      # cheap Claude, good single-step
    SONNET = "claude-sonnet"    # mid Claude, strong general
    OPUS = "claude-opus"        # expensive, reserve for genuinely hard stages


# Rough per-1k-token blended cost (input+output averaged). Tunable.
MODEL_COST_PER_1K = {
    StageModel.OLLAMA: 0.0,
    StageModel.PERPLEXITY: 0.001,
    StageModel.HAIKU: 0.0008,
    StageModel.SONNET: 0.006,
    StageModel.OPUS: 0.030,
}

# What each model can be trusted to do well enough to assign as a stage owner.
# Coarser than capability_map.py on purpose — stage-level, not call-level.
MODEL_FLOOR = {
    StageModel.OLLAMA: {"format", "explain", "summarize_local", "boilerplate"},
    StageModel.PERPLEXITY: {"research", "lookup", "current_events", "fact_check"},
    StageModel.HAIKU: {"format", "explain", "summarize_local", "boilerplate",
                       "simple_edit", "classify", "lint"},
    StageModel.SONNET: {"format", "explain", "summarize_local", "boilerplate",
                        "simple_edit", "classify", "lint", "code_gen",
                        "refactor_file", "test_write", "review"},
    StageModel.OPUS: {"format", "explain", "summarize_local", "boilerplate",
                      "simple_edit", "classify", "lint", "code_gen",
                      "refactor_file", "test_write", "review", "architecture",
                      "security_audit", "cross_file_migration", "adversarial_review"},
}


class StageKind(str, Enum):
    """What a stage is fundamentally doing — drives model floor + cost."""
    RESEARCH = "research"
    SUMMARIZE = "summarize_local"
    CLASSIFY = "classify"
    CODE_GEN = "code_gen"
    REFACTOR = "refactor_file"
    MIGRATION = "cross_file_migration"
    TEST = "test_write"
    REVIEW = "review"
    ADVERSARIAL = "adversarial_review"
    ARCHITECTURE = "architecture"
    SECURITY = "security_audit"
    FORMAT = "format"
    EXPLAIN = "explain"


# Stage kinds that genuinely justify the strongest model. Everything else
# should be challenged before it gets Opus.
HARD_KINDS = {
    StageKind.ARCHITECTURE,
    StageKind.SECURITY,
    StageKind.MIGRATION,
    StageKind.ADVERSARIAL,
}

# Typical fan-out (how many parallel subagents a stage tends to spawn) and
# rough tokens per agent. Used only for estimation; the runtime caps at
# 16 concurrent / 1000 total.
DEFAULT_FANOUT = {
    StageKind.RESEARCH: 8,
    StageKind.MIGRATION: 30,
    StageKind.REVIEW: 10,
    StageKind.ADVERSARIAL: 6,
    StageKind.SECURITY: 12,
    StageKind.CODE_GEN: 4,
    StageKind.REFACTOR: 8,
    StageKind.TEST: 6,
    StageKind.ARCHITECTURE: 3,
    StageKind.CLASSIFY: 2,
    StageKind.SUMMARIZE: 2,
    StageKind.FORMAT: 1,
    StageKind.EXPLAIN: 1,
}
TOKENS_PER_AGENT = 6000  # conservative average for a working subagent


@dataclass
class PlannedStage:
    name: str
    kind: StageKind
    assigned_model: StageModel
    rationale: str
    fanout: int
    est_tokens: int
    est_cost: float
    cheaper_alternative: StageModel | None = None
    cheaper_cost: float | None = None

    def to_routing_entry(self) -> dict:
        """The bit a workflow script consumes to route this stage."""
        return {"stage": self.name, "model": self.assigned_model.value}


@dataclass
class WorkflowPlan:
    task: str
    stages: list[PlannedStage]
    total_tokens: int
    total_cost: float
    governed_cost: float       # cost after applying cheapest-capable downgrades
    naive_opus_cost: float     # cost if every stage ran on Opus (the default trap)
    warnings: list[str] = field(default_factory=list)

    @property
    def savings_vs_naive(self) -> float:
        return self.naive_opus_cost - self.governed_cost

    def routing_spec(self) -> dict:
        """JSON spec to hand Claude: 'route stages per this spec'."""
        return {
            "task": self.task,
            "stage_models": [s.to_routing_entry() for s in self.stages],
        }

    def human_readable(self) -> str:
        lines = [
            f"WORKFLOW PLAN: {self.task}",
            "=" * 64,
        ]
        for i, s in enumerate(self.stages, 1):
            alt = ""
            if s.cheaper_alternative:
                alt = f"  (could drop to {s.cheaper_alternative.value} @ ${s.cheaper_cost:.2f})"
            lines.append(
                f"{i}. {s.name}  [{s.kind.value}]\n"
                f"   model: {s.assigned_model.value}  ×{s.fanout} agents  "
                f"~{s.est_tokens:,} tok  ${s.est_cost:.2f}{alt}\n"
                f"   why: {s.rationale}"
            )
        lines += [
            "-" * 64,
            f"Governed total:   ${self.governed_cost:.2f}  (~{self.total_tokens:,} tokens)",
            f"If all-Opus:      ${self.naive_opus_cost:.2f}",
            f"SAVED vs default: ${self.savings_vs_naive:.2f} "
            f"({(self.savings_vs_naive / self.naive_opus_cost * 100) if self.naive_opus_cost else 0:.0f}%)",
        ]
        if self.warnings:
            lines.append("-" * 64)
            lines += [f"⚠️  {w}" for w in self.warnings]
        return "\n".join(lines)


# ── Stage decomposition ───────────────────────────────────────────────────────
# Lightweight heuristic decomposition. For real use the workflow itself will
# decompose; GRIT's job is to anticipate the SHAPE so it can price + route it.
# Keyword → stage kind, intentionally simple and inspectable.

_KIND_SIGNALS: list[tuple[StageKind, tuple[str, ...]]] = [
    (StageKind.MIGRATION, ("migrat", "port ", "port from", "rewrite", "convert codebase", "upgrade across")),
    (StageKind.SECURITY, ("security", "auth check", "vulnerab", "injection", "secrets scan")),
    (StageKind.ARCHITECTURE, ("architect", "design system", "design the", "high-level design")),
    (StageKind.ADVERSARIAL, ("stress-test", "red team", "poke holes", "challenge the plan", "cross-check")),
    (StageKind.RESEARCH, ("research", "find sources", "look up", "investigate", "survey", "latest")),
    (StageKind.REVIEW, ("review", "audit", "code review", "check every")),
    (StageKind.TEST, ("write tests", "test coverage", "add tests", "unit test")),
    (StageKind.REFACTOR, ("refactor", "clean up", "extract", "rename across")),
    (StageKind.CODE_GEN, ("implement", "build", "write code", "create endpoint", "add feature")),
    (StageKind.SUMMARIZE, ("summarize", "summarise", "tl;dr", "digest")),
    (StageKind.CLASSIFY, ("classify", "categorize", "label", "triage")),
    (StageKind.FORMAT, ("format", "lint", "prettier", "style")),
    (StageKind.EXPLAIN, ("explain", "document", "describe")),
]


def infer_stage_kinds(task: str) -> list[StageKind]:
    """
    Infer the likely stages a workflow for this task will contain.
    Returns them in a sensible execution order. Always ends with a review/
    adversarial stage for anything non-trivial (mirrors how workflows verify).
    """
    t = task.lower()
    found: list[StageKind] = []
    for kind, signals in _KIND_SIGNALS:
        if any(sig in t for sig in signals):
            found.append(kind)

    if not found:
        # Unknown task: assume a modest code task.
        found = [StageKind.CODE_GEN]

    # De-dup preserving order.
    seen = set()
    ordered = []
    for k in found:
        if k not in seen:
            ordered.append(k)
            seen.add(k)

    # Anything with real work gets an adversarial verification tail, since the
    # native runtime supports cross-checking and it's cheap insurance.
    work_kinds = {StageKind.CODE_GEN, StageKind.REFACTOR, StageKind.MIGRATION,
                  StageKind.ARCHITECTURE, StageKind.SECURITY}
    if work_kinds & seen and StageKind.ADVERSARIAL not in seen:
        ordered.append(StageKind.ADVERSARIAL)

    return ordered


def cheapest_capable_model(kind: StageKind) -> tuple[StageModel, StageModel | None]:
    """
    Return (assigned, cheaper_alternative).
    assigned = cheapest model whose floor includes this kind.
    cheaper_alternative = the next cheaper model that ALMOST qualifies, surfaced
    so a human can choose to take the risk. None if assigned is already cheapest.
    """
    order = [StageModel.OLLAMA, StageModel.PERPLEXITY, StageModel.HAIKU,
             StageModel.SONNET, StageModel.OPUS]
    assigned = None
    for m in order:
        if kind.value in MODEL_FLOOR[m]:
            assigned = m
            break
    if assigned is None:
        assigned = StageModel.OPUS  # nothing claimed it → hardest tier

    # Hard kinds are never auto-downgraded below Sonnet.
    if kind in HARD_KINDS and order.index(assigned) < order.index(StageModel.SONNET):
        assigned = StageModel.SONNET

    idx = order.index(assigned)
    cheaper = order[idx - 1] if idx > 0 else None
    # Don't suggest a cheaper option for hard kinds — that's the whole point.
    if kind in HARD_KINDS:
        cheaper = None
    return assigned, cheaper


def plan_workflow(task: str, budget_ceiling: float | None = None) -> WorkflowPlan:
    """
    Produce a cost-annotated, model-routed plan for a task that will run as a
    Dynamic Workflow.
    """
    kinds = infer_stage_kinds(task)
    stages: list[PlannedStage] = []
    total_tokens = 0
    governed_cost = 0.0
    naive_opus_cost = 0.0
    warnings: list[str] = []

    for kind in kinds:
        fanout = DEFAULT_FANOUT.get(kind, 4)
        est_tokens = fanout * TOKENS_PER_AGENT
        assigned, cheaper = cheapest_capable_model(kind)

        est_cost = (est_tokens / 1000) * MODEL_COST_PER_1K[assigned]
        opus_cost = (est_tokens / 1000) * MODEL_COST_PER_1K[StageModel.OPUS]
        cheaper_cost = (
            (est_tokens / 1000) * MODEL_COST_PER_1K[cheaper] if cheaper else None
        )

        rationale = _rationale(kind, assigned)
        stages.append(PlannedStage(
            name=_stage_name(kind),
            kind=kind,
            assigned_model=assigned,
            rationale=rationale,
            fanout=fanout,
            est_tokens=est_tokens,
            est_cost=round(est_cost, 4),
            cheaper_alternative=cheaper,
            cheaper_cost=round(cheaper_cost, 4) if cheaper_cost is not None else None,
        ))
        total_tokens += est_tokens
        governed_cost += est_cost
        naive_opus_cost += opus_cost

    # Furnace warning: a lot of agents on an expensive model.
    opus_stages = [s for s in stages if s.assigned_model == StageModel.OPUS]
    if sum(s.fanout for s in opus_stages) >= 20:
        warnings.append(
            f"{sum(s.fanout for s in opus_stages)} Opus agents planned — "
            f"this is a token furnace. Consider scoping to a slice first."
        )

    if budget_ceiling is not None and governed_cost > budget_ceiling:
        warnings.append(
            f"Governed cost ${governed_cost:.2f} exceeds ceiling "
            f"${budget_ceiling:.2f}. Downgrade soft stages or scope down."
        )

    return WorkflowPlan(
        task=task,
        stages=stages,
        total_tokens=total_tokens,
        total_cost=round(governed_cost, 2),
        governed_cost=round(governed_cost, 2),
        naive_opus_cost=round(naive_opus_cost, 2),
        warnings=warnings,
    )


def _stage_name(kind: StageKind) -> str:
    return {
        StageKind.RESEARCH: "Research & source-gathering",
        StageKind.SUMMARIZE: "Summarize findings",
        StageKind.CLASSIFY: "Classify / triage",
        StageKind.CODE_GEN: "Implement changes",
        StageKind.REFACTOR: "Refactor",
        StageKind.MIGRATION: "Migrate / port files",
        StageKind.TEST: "Write & run tests",
        StageKind.REVIEW: "Review changes",
        StageKind.ADVERSARIAL: "Adversarial cross-check",
        StageKind.ARCHITECTURE: "Architecture / design",
        StageKind.SECURITY: "Security audit",
        StageKind.FORMAT: "Format / lint",
        StageKind.EXPLAIN: "Document / explain",
    }[kind]


def _rationale(kind: StageKind, model: StageModel) -> str:
    if model == StageModel.OLLAMA:
        return "Mechanical/local work — free local model is sufficient."
    if model == StageModel.PERPLEXITY:
        return "Needs web search; Perplexity has it built in at ~1/30th Opus cost."
    if model == StageModel.HAIKU:
        return "Simple single-step work — Haiku is accurate and cheap."
    if model == StageModel.SONNET:
        return "Real reasoning/codegen but not maximally hard — Sonnet handles it at ~1/5th Opus cost."
    return "Genuinely hard stage (architecture/security/migration/adversarial) — Opus justified."


# ── CLI demo ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    examples = [
        "Port our 500-file Python service from Flask to FastAPI and keep the test suite passing",
        "Research the top 10 DeFi protocols by TVL and cross-check their recent security audits",
        "Audit every API endpoint under src/routes/ for missing auth checks",
        "Format this file and add docstrings",
        "Build a landing page for a local bakery and write tests for the contact form",
    ]
    for ex in examples:
        plan = plan_workflow(ex, budget_ceiling=5.00)
        print(plan.human_readable())
        print("\nROUTING SPEC (hand this to Claude):")
        print(json.dumps(plan.routing_spec(), indent=2))
        print("\n" + "#" * 70 + "\n")
