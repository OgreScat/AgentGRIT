"""
GRIT Eval Task Suite

Fixed tasks with known-correct OUTCOMES. Each grader computes GRIT's actual
decision (via planner + governor) and grades the result against what a correct
cost-governor MUST do. These are the acceptance gates that gate trust promotion.

Design notes (per Anthropic eval guidance):
  - Grade outcomes, not paths: we assert the chosen model / verdict / cost, not
    the internal control flow.
  - Partial credit: each task has several weighted checks.
  - Critical checks (weight >= 1.0) hard-fail the task if they fail — e.g.
    "never downgrade a security stage" is non-negotiable.
  - Adversarial tasks included: phrasings designed to fool a naive keyword router
    (the exact brittleness we set out to fix).
"""

from __future__ import annotations

from src.workflow.planner import plan_workflow, StageKind, StageModel, HARD_KINDS
from src.workflow.cost_governor import govern_task, GovernorConfig, Verdict
from src.evals.harness import (
    EvalTask, CheckResult, check_equals, check_true, check_in,
)


# ── Routing-correctness tasks ─────────────────────────────────────────────────

def _g_research_to_perplexity() -> list[CheckResult]:
    plan = plan_workflow("Research the latest React 19 features and APIs")
    research = [s for s in plan.stages if s.kind == StageKind.RESEARCH]
    checks = [check_true(
        "has_research_stage", bool(research),
        "research stage present", "no research stage inferred",
    )]
    if research:
        checks.append(check_equals(
            "research_routed_to_perplexity",
            StageModel.PERPLEXITY, research[0].assigned_model,
        ))
    return checks


def _g_format_is_free() -> list[CheckResult]:
    plan = plan_workflow("Format this file and run the linter")
    fmt = [s for s in plan.stages if s.kind == StageKind.FORMAT]
    checks = [check_true("has_format_stage", bool(fmt),
                         "format stage present", "missing")]
    if fmt:
        checks.append(check_equals("format_uses_ollama",
                                   StageModel.OLLAMA, fmt[0].assigned_model))
        checks.append(check_true("format_is_free", fmt[0].est_cost == 0.0,
                                 "free", f"cost was ${fmt[0].est_cost}"))
    return checks


def _g_security_never_downgraded() -> list[CheckResult]:
    """CRITICAL: a security stage must never be auto-downgraded below Sonnet."""
    d = govern_task("Run a security audit on every endpoint in src/routes/")
    target = d.downgraded_plan or d.plan
    sec = [s for s in target.stages if s.kind == StageKind.SECURITY]
    checks = [check_true("has_security_stage", bool(sec),
                         "security stage present", "missing security stage")]
    for s in sec:
        checks.append(check_in(
            "security_model_floor", s.assigned_model,
            {StageModel.SONNET, StageModel.OPUS}, weight=2.0,  # critical
        ))
    return checks


# ── Adversarial routing (the brittleness we fixed) ────────────────────────────

def _g_research_architecture_not_naive() -> list[CheckResult]:
    """
    'Research the architecture of React' contains BOTH 'research' and
    'architecture'. A naive keyword router misroutes. We require the research
    stage to still go to Perplexity (web search), not get swallowed by Opus.
    """
    plan = plan_workflow("Research the architecture of popular React frameworks")
    research = [s for s in plan.stages if s.kind == StageKind.RESEARCH]
    checks = [check_true("research_survived_ambiguity", bool(research),
                         "research stage detected despite 'architecture' token",
                         "research stage lost to architecture keyword")]
    if research:
        checks.append(check_equals("ambiguous_research_to_perplexity",
                                   StageModel.PERPLEXITY, research[0].assigned_model))
    return checks


def _g_migration_gets_adversarial_tail() -> list[CheckResult]:
    plan = plan_workflow("Port the Flask codebase to FastAPI")
    kinds = {s.kind for s in plan.stages}
    return [
        check_true("migration_detected", StageKind.MIGRATION in kinds,
                   "migration stage present", "migration not detected"),
        check_true("adversarial_tail_added", StageKind.ADVERSARIAL in kinds,
                   "verification tail present", "no adversarial verification added"),
    ]


# ── Governor verdict tasks ────────────────────────────────────────────────────

def _g_free_task_allows() -> list[CheckResult]:
    d = govern_task("Format this file and add docstrings")
    return [check_equals("verdict", Verdict.ALLOW, d.verdict)]


def _g_expensive_escalates_when_untrusted() -> list[CheckResult]:
    d = govern_task(
        "Port our 500-file service from Flask to FastAPI and keep tests passing",
        GovernorConfig(trust_level="UNTRUSTED"),
    )
    return [check_equals("verdict_escalate", Verdict.ESCALATE, d.verdict, weight=2.0)]


def _g_autonomous_bypasses() -> list[CheckResult]:
    d = govern_task(
        "Port our 500-file service from Flask to FastAPI and keep tests passing",
        GovernorConfig(trust_level="AUTONOMOUS"),
    )
    return [check_in("verdict_auto", d.verdict,
                     {Verdict.ALLOW, Verdict.DOWNGRADE}, weight=2.0)]


def _g_hard_ceiling_blocks() -> list[CheckResult]:
    d = govern_task("Port our 500-file service from Flask to FastAPI",
                    GovernorConfig(hard_ceiling=0.50))
    return [check_equals("verdict_block", Verdict.BLOCK, d.verdict, weight=2.0)]


def _g_mixed_task_saves_money() -> list[CheckResult]:
    d = govern_task("Research DeFi protocols, review findings, and summarize them")
    target = d.downgraded_plan or d.plan
    saves = target.governed_cost < d.plan.naive_opus_cost
    return [
        check_true("cheaper_than_all_opus", saves,
                   f"governed ${target.governed_cost} < all-opus ${d.plan.naive_opus_cost}",
                   "governed plan not cheaper than naive all-Opus"),
    ]


def _g_downgrade_preserves_hard() -> list[CheckResult]:
    """CRITICAL: downgrading must never touch hard stages."""
    d = govern_task("Migrate the codebase and run a security audit")
    target = d.downgraded_plan or d.plan
    checks = []
    for s in target.stages:
        if s.kind in HARD_KINDS:
            checks.append(check_in(
                f"hard_stage_preserved::{s.kind.value}", s.assigned_model,
                {StageModel.SONNET, StageModel.OPUS}, weight=2.0,
            ))
    if not checks:
        checks.append(check_true("had_hard_stage", False,
                                 "", "no hard stage found to verify"))
    return checks


def _g_telegram_payload_wellformed() -> list[CheckResult]:
    d = govern_task("Research DeFi protocols and review findings")
    p = d.telegram_payload()
    required = {"verdict", "task", "cost", "stages", "needs_human", "routing_spec"}
    missing = required - set(p.keys())
    return [check_true("payload_complete", not missing,
                       "all keys present", f"missing keys: {missing}", weight=2.0)]


# ── The suite ─────────────────────────────────────────────────────────────────

SUITE: list[EvalTask] = [
    EvalTask("route-research", "Research routes to Perplexity",
             _g_research_to_perplexity, pattern="routing"),
    EvalTask("route-format-free", "Format routes to free local model",
             _g_format_is_free, pattern="routing"),
    EvalTask("route-security-floor", "Security never downgraded below Sonnet",
             _g_security_never_downgraded, pattern="safety"),
    EvalTask("adv-research-architecture", "Ambiguous 'research architecture' not misrouted",
             _g_research_architecture_not_naive, pattern="routing"),
    EvalTask("flow-migration-tail", "Migration gets adversarial verification tail",
             _g_migration_gets_adversarial_tail, pattern="flow"),
    EvalTask("gov-free-allows", "Free task is auto-allowed",
             _g_free_task_allows, pattern="governance"),
    EvalTask("gov-expensive-escalates", "Expensive run escalates when untrusted",
             _g_expensive_escalates_when_untrusted, pattern="governance"),
    EvalTask("gov-autonomous-bypass", "Autonomous trust bypasses escalation",
             _g_autonomous_bypasses, pattern="governance"),
    EvalTask("gov-ceiling-blocks", "Hard ceiling blocks runaway spend",
             _g_hard_ceiling_blocks, pattern="safety"),
    EvalTask("gov-mixed-saves", "Mixed task cheaper than naive all-Opus",
             _g_mixed_task_saves_money, pattern="cost"),
    EvalTask("gov-downgrade-preserves", "Downgrade preserves hard stages",
             _g_downgrade_preserves_hard, pattern="safety"),
    EvalTask("gov-telegram-payload", "Telegram approval payload well-formed",
             _g_telegram_payload_wellformed, pattern="integration"),
]


def get_suite() -> list[EvalTask]:
    return SUITE
