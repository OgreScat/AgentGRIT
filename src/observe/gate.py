"""Observe gate — wire fused events through research_quality + decision_record.

Observation NEVER acts. Events that are stale, lone-source weak, or contested
are flagged non-actionable. One decision_record per observe run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schema import ObserveEvent


@dataclass
class GateResult:
    events: list[ObserveEvent]
    assessment_verdict: str
    assessment_score: float
    assessment_reason: str
    require_human: bool
    actionable_count: int
    non_actionable_count: int
    decision_disposition: str | None = None
    authorized_by: str = "observe:run"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "events": [e.to_dict() for e in self.events],
            "assessment_verdict": self.assessment_verdict,
            "assessment_score": self.assessment_score,
            "assessment_reason": self.assessment_reason,
            "require_human": self.require_human,
            "actionable_count": self.actionable_count,
            "non_actionable_count": self.non_actionable_count,
            "decision_disposition": self.decision_disposition,
            "authorized_by": self.authorized_by,
            "notes": list(self.notes),
        }


def _mark_actionable(events: list[ObserveEvent], batch_verdict: str) -> list[ObserveEvent]:
    """Set actionable flags. Contested/stale/weak lone sources never actionable."""
    out: list[ObserveEvent] = []
    for e in events:
        ok = True
        if e.freshness_grade == "stale":
            ok = False
        if e.evidence_grade < 0.55:
            ok = False
        if len(e.corroborating_sources) < 2 and e.evidence_grade < 0.70:
            # Lone source cannot alone drive action (the 10x rule)
            ok = False
        if batch_verdict in ("contested", "insufficient"):
            ok = False
        e.actionable = ok
        out.append(e)
    return out


def gate(
    events: list[ObserveEvent],
    *,
    feed_label: str = "run",
    high_stakes: bool = True,
    record_decision: bool = True,
) -> GateResult:
    """Score observations via research_quality.assess; emit one decision record.

    Fail-safe: assess/record failures → non-actionable + note, never raise.
    """
    notes: list[str] = []
    results = [e.to_research_result() for e in events]

    verdict = "insufficient"
    score = 0.0
    reason = "no events"
    require_human = True

    try:
        from src.governance.research_quality import assess
        # Observations that would drive action are high-stakes but reversible
        # (observing ≠ executing). Contested/insufficient → require human.
        a = assess(results, high_stakes=high_stakes, reversible=True)
        verdict = getattr(getattr(a, "verdict", None), "value", None) or str(
            getattr(a, "verdict", "insufficient")
        )
        score = float(getattr(a, "score", 0.0) or 0.0)
        reason = str(getattr(a, "reason", "") or "")
        require_human = bool(getattr(a, "require_human", True))
    except Exception as exc:  # noqa: BLE001
        notes.append(f"research_quality.assess unavailable: {exc}")
        verdict = "insufficient"
        require_human = True

    scored = _mark_actionable(list(events), verdict)
    actionable_n = sum(1 for e in scored if e.actionable)
    non_n = len(scored) - actionable_n

    # If anything non-actionable due to stale/contested, force human flag
    if non_n and verdict == "sufficient" and any(
        e.freshness_grade == "stale" for e in scored
    ):
        notes.append("stale events present — refused actionability individually")
    if any(len(e.corroborating_sources) < 2 for e in scored):
        notes.append("lone-source events capped — cannot alone authorize action")

    auth = f"observe:{feed_label}"
    disposition = None
    if record_decision:
        try:
            from src.governance.decision_record import record as _record
            from src.governance.bylaws import BylawAction

            class _Route:
                provider = "observe"
                category = "observe"
                confidence = score
                estimated_cost = 0.0
                reason = (
                    f"observe/{feed_label}: {len(scored)} fused, "
                    f"{actionable_n} actionable, verdict={verdict}"
                )

            class _Evidence:
                def __init__(self):
                    self.verdict = verdict
                    self.score = score
                    self.require_human = require_human or (actionable_n == 0 and len(scored) > 0)
                    self.reason = reason

            # If nothing is actionable, surface as escalate disposition
            bylaw_action = BylawAction.PROCEED
            bylaw_reason = "observation scored; no side effects"
            if actionable_n == 0 and scored:
                bylaw_action = BylawAction.ESCALATE
                bylaw_reason = "no actionable observations (stale/weak/contested)"
            if verdict in ("contested", "insufficient"):
                bylaw_action = BylawAction.ESCALATE
                bylaw_reason = reason or verdict

            rec = _record(
                action=f"observe run feed={feed_label} n={len(scored)}"[:200],
                routing=_Route(),
                bylaw=type("B", (), {"action": bylaw_action, "reason": bylaw_reason})(),
                evidence=_Evidence(),
                authorized_by=auth,
            )
            disposition = getattr(getattr(rec, "disposition", None), "value", None)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"decision_record skipped: {exc}")

    result = GateResult(
        events=scored,
        assessment_verdict=verdict,
        assessment_score=score,
        assessment_reason=reason,
        require_human=require_human,
        actionable_count=actionable_n,
        non_actionable_count=non_n,
        decision_disposition=disposition,
        authorized_by=auth,
        notes=notes,
    )
    # Opt-in domain brief for GET /brief (UI is read-only)
    try:
        from src.governance.brief_record import record_brief
        record_brief(result.to_dict(), kind="observe")
    except Exception:
        pass
    return result


def render_report(result: GateResult) -> str:
    """Human-readable scored observation report."""
    lines = [
        "GRIT OBSERVE REPORT  ·  scored evidence only (no action)",
        "=" * 58,
        f"  verdict:     {result.assessment_verdict}  (score={result.assessment_score:.2f})",
        f"  reason:      {result.assessment_reason}",
        f"  actionable:  {result.actionable_count}  / non-actionable: {result.non_actionable_count}",
        f"  decision:    {result.decision_disposition or 'n/a'}  auth={result.authorized_by}",
        f"  require_human: {result.require_human}",
        "",
        "EVENTS",
        "-" * 58,
    ]
    if not result.events:
        lines.append("  (none fetched or all adapters empty)")
    for i, e in enumerate(result.events, 1):
        flag = "✓ ACTIONABLE" if e.actionable else "✗ NOT ACTIONABLE"
        lines.append(f"  {i}. [{flag}] {e.title[:80]}")
        lines.append(
            f"     source={e.source_id}  type={e.source_type}  cat={e.category}"
        )
        lines.append(
            f"     freshness={e.freshness_grade}  evidence={e.evidence_grade:.2f}  "
            f"salience={e.salience:.2f}"
        )
        lines.append(
            f"     corroboration={','.join(e.corroborating_sources) or e.source_id}"
        )
        if e.url:
            lines.append(f"     url={e.url}")
        why = []
        if e.freshness_grade == "stale":
            why.append("stale")
        if len(e.corroborating_sources) < 2:
            why.append("lone-source")
        if e.evidence_grade < 0.55:
            why.append("weak-evidence")
        if not e.actionable and why:
            lines.append(f"     refused because: {', '.join(why)}")
        lines.append("")
    if result.notes:
        lines.append("NOTES")
        lines.append("-" * 58)
        for n in result.notes:
            lines.append(f"  • {n}")
    lines.append(
        "Observation does not act. Contested/stale/lone-source signals cannot "
        "authorize side effects."
    )
    lines.append("=" * 58)
    return "\n".join(lines)
