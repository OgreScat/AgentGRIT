"""
Native Pillar Inspector -- the iFixAi misalignment pillars, re-engineered as
first-class, DETERMINISTIC, pre-execution gates inside GRIT's governance loop.

Runs before every high-stakes action and produces a governance scorecard the GM
attaches to its escalation. Deterministic on purpose: a governance self-check
must not itself be an opaque model. The five pillars map onto GRIT's bylaws:

  FABRICATION      Is the action backed by SUFFICIENT-QUALITY evidence, not an
                   unsourced or weak-sourced claim? (weak research fails this)
  MANIPULATION     Stays in scope, no privilege escalation / forbidden paths?
  DECEPTION        Visible intent matches the action (no covert side effects)?
  UNPREDICTABILITY Reversible / deterministic, or drifting from the task?
  OPACITY          Logged and traceable?

Fabrication now judges evidence QUALITY, not mere presence -- so an irreversible
action resting on a single weak web result fails Fabrication and forces review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Pillar(Enum):
    FABRICATION = "fabrication"
    MANIPULATION = "manipulation"
    DECEPTION = "deception"
    UNPREDICTABILITY = "unpredictability"
    OPACITY = "opacity"


@dataclass
class PillarResult:
    pillar: Pillar
    passed: bool
    detail: str


@dataclass
class Scorecard:
    results: list[PillarResult] = field(default_factory=list)

    @property
    def score(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.passed) / len(self.results)

    @property
    def grade(self) -> str:
        s = self.score
        return ("A" if s >= 0.90 else "B" if s >= 0.80 else
                "C" if s >= 0.70 else "D" if s >= 0.60 else "F")

    def flagged(self) -> list[PillarResult]:
        return [r for r in self.results if not r.passed]

    def summary(self) -> str:
        bad = self.flagged()
        if not bad:
            return f"grade {self.grade} ({self.score:.0%}) · all pillars pass"
        names = ", ".join(r.pillar.value for r in bad)
        return f"grade {self.grade} ({self.score:.0%}) · flags: {names}"


@dataclass
class Proposal:
    """What the junior/manager proposes, plus the signals the pillars judge."""
    action: str
    evidence: str = ""            # cited research/sources backing the action
    evidence_quality: float = 1.0   # 0..1 from research_quality.assess (default: trusted)
    intent: str = ""
    reversible: bool = True
    in_scope: bool = True
    touches_forbidden: bool = False
    logged: bool = True
    covert_side_effects: bool = False


# Below this quality, evidence is not strong enough to satisfy Fabrication.
EVIDENCE_QUALITY_BAR = 0.60


def inspect(p: Proposal) -> Scorecard:
    """Score a proposal against the five pillars. Pure, deterministic."""
    has_ev = bool(p.evidence.strip())
    good_ev = has_ev and p.evidence_quality >= EVIDENCE_QUALITY_BAR
    if not has_ev:
        fab_detail = "no evidence cited"
    elif good_ev:
        fab_detail = f"evidence cited (quality {p.evidence_quality:.2f})"
    else:
        fab_detail = f"evidence too weak to act on (quality {p.evidence_quality:.2f} < {EVIDENCE_QUALITY_BAR})"

    r = [
        PillarResult(Pillar.FABRICATION, good_ev, fab_detail),
        PillarResult(Pillar.MANIPULATION, (not p.touches_forbidden) and p.in_scope,
                     "in scope, no forbidden access" if (not p.touches_forbidden and p.in_scope)
                     else "out of scope or touches forbidden path"),
        PillarResult(Pillar.DECEPTION, not p.covert_side_effects,
                     "action matches stated intent" if not p.covert_side_effects
                     else "action exceeds stated intent"),
        PillarResult(Pillar.UNPREDICTABILITY, p.reversible,
                     "reversible" if p.reversible else "irreversible action"),
        PillarResult(Pillar.OPACITY, p.logged,
                     "logged and traceable" if p.logged else "not logged"),
    ]
    return Scorecard(r)


if __name__ == "__main__":
    demos = [
        Proposal(action="add docstrings", evidence="style guide", evidence_quality=0.9,
                 intent="readability"),
        Proposal(action="delete build artifacts", evidence="one web hit",
                 evidence_quality=0.45, intent="cleanup", reversible=False),
        Proposal(action="rotate API key", evidence="rotation policy", evidence_quality=0.9,
                 intent="cleanup", touches_forbidden=True, covert_side_effects=True,
                 reversible=False),
    ]
    for d in demos:
        print(f"{d.action:24} -> {inspect(d).summary()}")
