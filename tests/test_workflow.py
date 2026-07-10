"""
Tests for GRIT workflow planner + cost governor.

These are the acceptance gates for the re-positioned GRIT: the cost-governance
layer must (a) never downgrade a genuinely-hard stage, (b) actually save money
on mixed tasks, (c) escalate/block runaway spend, and (d) emit a valid routing
spec.
"""

import pytest

from src.workflow.planner import (
    plan_workflow, infer_stage_kinds, cheapest_capable_model,
    StageKind, StageModel, HARD_KINDS,
)
from src.workflow.cost_governor import (
    govern, govern_task, GovernorConfig, Verdict,
)


# ── Planner ───────────────────────────────────────────────────────────────────

def test_research_routes_to_perplexity_not_opus():
    plan = plan_workflow("Research the latest React 19 features")
    research = [s for s in plan.stages if s.kind == StageKind.RESEARCH]
    assert research, "expected a research stage"
    assert research[0].assigned_model == StageModel.PERPLEXITY


def test_format_routes_to_free_local():
    plan = plan_workflow("Format this file and lint it")
    fmt = [s for s in plan.stages if s.kind == StageKind.FORMAT]
    assert fmt
    assert fmt[0].assigned_model == StageModel.OLLAMA
    assert fmt[0].est_cost == 0.0


def test_hard_kinds_never_downgraded_below_sonnet():
    for kind in HARD_KINDS:
        assigned, cheaper = cheapest_capable_model(kind)
        order = [StageModel.OLLAMA, StageModel.PERPLEXITY, StageModel.HAIKU,
                 StageModel.SONNET, StageModel.OPUS]
        assert order.index(assigned) >= order.index(StageModel.SONNET)
        assert cheaper is None, f"{kind} must not offer a cheaper alternative"


def test_migration_implies_adversarial_tail():
    kinds = infer_stage_kinds("Port the codebase from Flask to FastAPI")
    assert StageKind.MIGRATION in kinds
    assert StageKind.ADVERSARIAL in kinds, "hard work should get a verification tail"


def test_mixed_task_saves_vs_naive_opus():
    plan = plan_workflow(
        "Research DeFi protocols, review the findings, and summarize them"
    )
    assert plan.governed_cost < plan.naive_opus_cost
    assert plan.savings_vs_naive > 0


def test_routing_spec_is_wellformed():
    plan = plan_workflow("Implement a feature and write tests")
    spec = plan.routing_spec()
    assert "task" in spec and "stage_models" in spec
    for entry in spec["stage_models"]:
        assert "stage" in entry and "model" in entry
        # model must be a real StageModel value
        StageModel(entry["model"])


def test_unknown_task_defaults_to_codegen():
    kinds = infer_stage_kinds("do the thing with the stuff")
    assert StageKind.CODE_GEN in kinds


# ── Governor ──────────────────────────────────────────────────────────────────

def test_free_task_allows():
    d = govern_task("Format this file and add docstrings")
    assert d.verdict == Verdict.ALLOW


def test_mixed_task_offers_downgrade():
    d = govern_task(
        "Research DeFi protocols, review the findings, and summarize them"
    )
    assert d.verdict in (Verdict.DOWNGRADE, Verdict.ALLOW)
    if d.verdict == Verdict.DOWNGRADE:
        assert d.downgraded_plan is not None
        assert d.downgraded_plan.governed_cost <= d.plan.governed_cost


def test_expensive_migration_escalates_when_untrusted():
    d = govern_task(
        "Port our 500-file service from Flask to FastAPI and keep tests passing",
        GovernorConfig(trust_level="UNTRUSTED"),
    )
    assert d.verdict == Verdict.ESCALATE


def test_autonomous_trust_bypasses_escalation():
    d = govern_task(
        "Port our 500-file service from Flask to FastAPI and keep tests passing",
        GovernorConfig(trust_level="AUTONOMOUS"),
    )
    assert d.verdict in (Verdict.ALLOW, Verdict.DOWNGRADE)


def test_hard_ceiling_blocks():
    # Force a tiny ceiling so any real plan trips it.
    d = govern_task(
        "Port our 500-file service from Flask to FastAPI",
        GovernorConfig(hard_ceiling=0.50),
    )
    assert d.verdict == Verdict.BLOCK


def test_downgrade_preserves_hard_stages():
    d = govern_task(
        "Migrate the codebase and run a security audit",
        GovernorConfig(),
    )
    target = d.downgraded_plan or d.plan
    for s in target.stages:
        if s.kind in HARD_KINDS:
            assert s.assigned_model in (StageModel.SONNET, StageModel.OPUS)


def test_telegram_payload_shape():
    d = govern_task("Research DeFi protocols and review findings")
    payload = d.telegram_payload()
    for key in ("verdict", "task", "cost", "stages", "needs_human", "routing_spec"):
        assert key in payload


def test_execution_order_research_before_review():
    d = govern_task("Review the code then research alternatives")
    kinds = [s.kind for s in d.plan.stages]
    if StageKind.RESEARCH in kinds and StageKind.REVIEW in kinds:
        assert kinds.index(StageKind.RESEARCH) < kinds.index(StageKind.REVIEW)
