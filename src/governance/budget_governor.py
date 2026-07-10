"""
Budget Governor -- one read surface over the budget sources that already exist.

AgentGRIT historically tracked spend in three places that never talked to each
other:

  1. workflow cost thresholds  -- src/workflow/cost_governor.GovernorConfig
     (soft_budget=$2, escalate_budget=$5, hard_ceiling=$25)
  2. research paid-call cap    -- RESEARCH_MAX_PAID_PER_DAY (default 25) +
     logs/research_budget.jsonl  (src/execution/research.py)
  3. router UsageTracker       -- Perplexity monthly budget field on the
     in-process tracker (src/execution/router.py MODEL_COSTS / UsageTracker)

This module does NOT invent costs or re-route models. It:
  * exposes a single status() that reports live research paid-call usage
  * applies the SAME dollar thresholds as cost_governor.GovernorConfig to a
    plain estimated-USD figure (for call sites that have a number, not a plan)
  * delegates full WorkflowPlan governance to cost_governor.govern() so there
    is one policy, not two

Dollar defaults are copied from GovernorConfig fields at import time and can
be overridden via env without renaming any keys:

  GRIT_SOFT_BUDGET / GRIT_ESCALATE_BUDGET / GRIT_HARD_CEILING

Research cap remains RESEARCH_MAX_PAID_PER_DAY (unchanged contract).
"""

from __future__ import annotations

import os
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

    def to_entry(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "estimated_usd": self.estimated_usd,
            "reasons": list(self.reasons),
            "trust_level": self.trust_level,
        }


def _thresholds() -> BudgetThresholds:
    # Defaults mirror GovernorConfig exactly (cost_governor.py lines 61-63).
    soft = float(os.environ.get("GRIT_SOFT_BUDGET", "2.00"))
    escalate = float(os.environ.get("GRIT_ESCALATE_BUDGET", "5.00"))
    hard = float(os.environ.get("GRIT_HARD_CEILING", "25.00"))
    max_paid = int(os.environ.get("RESEARCH_MAX_PAID_PER_DAY", "25"))
    return BudgetThresholds(soft, escalate, hard, max_paid)


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
) -> BudgetDecision:
    """Apply cost_governor dollar thresholds to a single estimated-USD figure.

    Trust=AUTONOMOUS may auto-clear an over-escalate figure (same rule as
    cost_governor.govern lines 185-189). Hard ceiling always BLOCKs.
    """
    thr = _thresholds()
    cost = float(estimated_usd)
    tl = (trust_level or "UNTRUSTED").upper()
    reasons: list[str] = []

    if cost > thr.hard_ceiling:
        reasons.append(
            f"Estimated ${cost:.2f} exceeds hard ceiling ${thr.hard_ceiling:.2f}."
        )
        return BudgetDecision(BudgetVerdict.BLOCK, cost, reasons, tl)

    if cost > thr.escalate_budget:
        reasons.append(
            f"Estimated ${cost:.2f} exceeds escalate budget ${thr.escalate_budget:.2f}."
        )
        if tl == "AUTONOMOUS":
            reasons.append("Trust=AUTONOMOUS -> auto-approved despite cost.")
            return BudgetDecision(BudgetVerdict.ALLOW, cost, reasons, tl)
        return BudgetDecision(BudgetVerdict.ESCALATE, cost, reasons, tl)

    if cost > thr.soft_budget:
        reasons.append(
            f"Estimated ${cost:.2f} over soft budget ${thr.soft_budget:.2f}."
        )
        return BudgetDecision(BudgetVerdict.DOWNGRADE, cost, reasons, tl)

    reasons.append(f"Within budget at ${cost:.2f}.")
    return BudgetDecision(BudgetVerdict.ALLOW, cost, reasons, tl)


def govern_plan(plan: Any, trust_level: str = "UNTRUSTED") -> Any:
    """Delegate full WorkflowPlan governance to cost_governor (single policy)."""
    from src.workflow.cost_governor import govern, GovernorConfig
    return govern(plan, GovernorConfig(trust_level=trust_level.upper()))


if __name__ == "__main__":
    s = status()
    print("thresholds:", s.thresholds.to_entry())
    print("research paid today:", s.research_paid_today, "remaining:", s.research_remaining)
    for usd in (0.5, 3.0, 8.0, 30.0):
        d = check_estimated_usd(usd, "UNTRUSTED")
        print(f"  ${usd:.2f} -> {d.verdict.value}: {d.reasons[0]}")
