"""Priority manager + budget_governor live on cost_governor path."""

from pathlib import Path

from src.governance.priority_manager import (
    weight_for, is_high_priority, budget_scale, detect_project_from_task,
)
from src.governance.budget_governor import check_estimated_usd, BudgetVerdict
from src.workflow.planner import plan_workflow, StageKind, StageModel, PlannedStage, WorkflowPlan
from src.workflow.cost_governor import govern, GovernorConfig, Verdict


def test_default_weight_neutral():
    # weight 0.5 → scale 1.0
    assert abs(budget_scale(0.5) - 1.0) < 1e-9
    assert weight_for(None) == 0.5


def test_weight_from_config(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "priorities.yaml").write_text(
        "default_weight: 0.5\nhigh_priority_threshold: 0.75\n"
        "projects:\n  critical-app: 0.9\n  toy: 0.2\n"
    )
    monkeypatch.setenv("GRIT_CONFIG_DIR", str(cfg_dir))
    # reload via fresh calls (no module-level cache of file contents)
    assert weight_for("critical-app") == 0.9
    assert weight_for("toy") == 0.2
    assert is_high_priority("critical-app")
    assert not is_high_priority("toy")


def test_detect_project_from_priorities(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "priorities.yaml").write_text(
        "default_weight: 0.5\nprojects:\n  billing-service: 0.95\n"
    )
    monkeypatch.setenv("GRIT_CONFIG_DIR", str(cfg_dir))
    assert detect_project_from_task("refactor the billing-service auth module") == "billing-service"


def test_high_priority_protected_from_soft_downgrade(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "budget.yaml").write_text(
        "soft_budget: 2.00\nescalate_budget: 5.00\nhard_ceiling: 25.00\n"
        "research_max_paid_per_day: 25\n"
    )
    (cfg_dir / "priorities.yaml").write_text(
        "default_weight: 0.5\nhigh_priority_threshold: 0.75\n"
        "projects:\n  critical-app: 0.95\n  toy: 0.1\n"
    )
    monkeypatch.setenv("GRIT_CONFIG_DIR", str(cfg_dir))

    # $3 is over soft ($2) for low priority → DOWNGRADE
    low = check_estimated_usd(3.0, "UNTRUSTED", project="toy")
    assert low.verdict is BudgetVerdict.DOWNGRADE

    # Same $3 for high priority → ALLOW (protected)
    high = check_estimated_usd(3.0, "UNTRUSTED", project="critical-app")
    assert high.verdict is BudgetVerdict.ALLOW
    assert any("high priority" in r.lower() or "protected" in r.lower() for r in high.reasons)


def test_hard_ceiling_ignores_priority(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "budget.yaml").write_text(
        "soft_budget: 2.00\nescalate_budget: 5.00\nhard_ceiling: 25.00\n"
        "research_max_paid_per_day: 25\n"
    )
    (cfg_dir / "priorities.yaml").write_text(
        "projects:\n  critical-app: 1.0\n"
    )
    monkeypatch.setenv("GRIT_CONFIG_DIR", str(cfg_dir))
    d = check_estimated_usd(30.0, "AUTONOMOUS", project="critical-app")
    assert d.verdict is BudgetVerdict.BLOCK


def test_cost_governor_calls_budget_for_downgrade(tmp_path, monkeypatch):
    """Live path: govern() must invoke priority-aware budget (non-test caller)."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "priorities.yaml").write_text(
        "default_weight: 0.5\nhigh_priority_threshold: 0.75\n"
        "projects:\n  toy: 0.1\n"
    )
    monkeypatch.setenv("GRIT_CONFIG_DIR", str(cfg_dir))

    # A plan with soft stages that can downgrade; GovernorConfig sets soft tiny
    # and escalate high so we hit DOWNGRADE (not ESCALATE/BLOCK).
    plan = plan_workflow(
        "Research the docs, summarize findings, and format the report for toy"
    )
    assert plan.governed_cost > 0.01
    cfg = GovernorConfig(
        soft_budget=0.01,
        escalate_budget=100.0,
        hard_ceiling=200.0,
        trust_level="UNTRUSTED",
    )
    d = govern(plan, cfg, project="toy")
    assert d.verdict == Verdict.DOWNGRADE
    assert d.downgraded_plan is not None
    assert any("soft" in r.lower() or "downgrade" in r.lower() for r in d.reasons)
