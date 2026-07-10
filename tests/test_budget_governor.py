"""Budget Governor -- facade over real thresholds; no invented numbers."""

from src.governance.budget_governor import (
    BudgetVerdict,
    check_estimated_usd,
    status,
    allow_paid_research,
)
from src.workflow.cost_governor import GovernorConfig


def test_thresholds_match_cost_governor_defaults():
    cfg = GovernorConfig()
    s = status()
    assert s.thresholds.soft_budget == cfg.soft_budget
    assert s.thresholds.escalate_budget == cfg.escalate_budget
    assert s.thresholds.hard_ceiling == cfg.hard_ceiling


def test_within_soft_allows():
    d = check_estimated_usd(0.50, "UNTRUSTED")
    assert d.verdict is BudgetVerdict.ALLOW


def test_over_soft_is_downgrade():
    d = check_estimated_usd(3.00, "UNTRUSTED")
    assert d.verdict is BudgetVerdict.DOWNGRADE


def test_over_escalate_is_escalate():
    d = check_estimated_usd(8.00, "UNTRUSTED")
    assert d.verdict is BudgetVerdict.ESCALATE


def test_over_escalate_autonomous_allows():
    d = check_estimated_usd(8.00, "AUTONOMOUS")
    assert d.verdict is BudgetVerdict.ALLOW
    assert any("AUTONOMOUS" in r for r in d.reasons)


def test_hard_ceiling_blocks_even_autonomous():
    d = check_estimated_usd(30.00, "AUTONOMOUS")
    assert d.verdict is BudgetVerdict.BLOCK


def test_status_has_research_fields():
    s = status()
    assert s.research_paid_today >= 0
    assert s.research_remaining >= 0
    assert isinstance(s.research_capped, bool)
    # allow_paid_research is the inverse of capped
    assert allow_paid_research() is (not s.research_capped)
