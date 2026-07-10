"""In-house skill review -- JR finds, GRIT reviews, GM green-lights. Keep humans rare.

Doctrine: the ideal is trustworthy automation, not a human rubber-stamp on every install.
So a discovered skill is NOT sent to you by default. It is reviewed here on deterministic
merits -- source reputation, permission surface, code execution, relevance -- and the GM
auto-green-lights anything that clears the bar within its trust ceiling. It also auto-
REJECTS the clearly-bad (a refusal is a complete decision -- no human needed). Only the
genuinely consequential residue reaches you: a skill that wants your secrets, runs
arbitrary code from an unvetted source, or is proposed for a high-stakes context.

This is the supply-chain analogue of the research-quality gate: automate the clearly-good
and the clearly-bad; escalate only the ambiguous-and-consequential. It maps to the tiers:
JR surfaces + scores relevance, this review is the Manager's security/merit judgment, and
`auto_greenlight` is the GM acting within the autonomy threshold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Decision(Enum):
    APPROVE = "approve"   # GM green-lights, no human
    REVIEW = "review"     # a closer look; human only if consequential
    REJECT = "reject"     # auto-denied, no human (a refusal is complete)


# Permission tokens a skill may request.
DANGEROUS = {"secrets", "credentials", "keys"}
BROAD = {"filesystem", "network", "shell", "exec"}


@dataclass
class SkillVerdict:
    decision: Decision
    auto_greenlight: bool
    requires_human: bool
    reasons: list = field(default_factory=list)


def review(skill, relevance: float, *, vetted: bool, high_stakes: bool = False,
           relevance_bar: float = 0.34) -> SkillVerdict:
    """Deterministic merit review of a discovered skill. Never raises."""
    perms = set(getattr(skill, "permissions", ()) or ())
    dangerous = bool(perms & DANGEROUS)
    broad = bool(perms & BROAD)
    runs_code = bool(getattr(skill, "runs_code", True))
    reasons: list[str] = []

    # auto-REJECT: unvetted source that runs code broadly or wants secrets.
    if not vetted and (dangerous or (runs_code and broad)):
        reasons.append("unvetted source requesting dangerous/broad access -> reject")
        return SkillVerdict(Decision.REJECT, auto_greenlight=False,
                            requires_human=False, reasons=reasons)

    # auto-APPROVE: vetted, no secret access, relevant, not high-stakes.
    if vetted and not dangerous and relevance >= relevance_bar and not high_stakes:
        reasons.append("vetted source, bounded permissions, relevant -> GM green-lights")
        return SkillVerdict(Decision.APPROVE, auto_greenlight=True,
                            requires_human=False, reasons=reasons)

    # otherwise REVIEW -- human only for the consequential residue.
    requires_human = dangerous or high_stakes or (not vetted and runs_code)
    if dangerous:
        reasons.append("requests secret/credential access")
    if high_stakes:
        reasons.append("high-stakes context")
    if not vetted and runs_code:
        reasons.append("unvetted source that runs code")
    if not requires_human:
        reasons.append("mixed but bounded -> Manager clears it without you")
    return SkillVerdict(Decision.REVIEW, auto_greenlight=not requires_human,
                        requires_human=requires_human, reasons=reasons)
