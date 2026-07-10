"""
Decision Record -- the auditable "why" behind every consequential action.

This is GRIT's un-forkable artifact. For any decision that mattered it records,
in one reproducible line of evidence:

  * WHAT was decided (the action + final disposition)
  * WHICH cheaper options were passed over, and the honest reason they weren't used
  * WHAT evidence backed it -- with provenance score and the research verdict
  * WHY it was refused, escalated, or flagged as contested
  * WHO (or which threshold) authorized it

It RECORDS; it does not DECIDE. The disposition is computed upstream by the
router (cost-first choice), the bylaw engine (hard gates), and research_quality
(evidence + conflict detection). This module composes their outputs into one
honest record. Every field traces to a real upstream result -- nothing here is
invented, estimated-as-fact, or asserted beyond what the caller supplied. That
discipline is the point: a decision record you can trust is one that never
contains a number no tool produced.

Append-only to logs/decisions.jsonl (rotated, fail-safe). Renders to plain text
a human or auditor can read without the code -- the compliance artifact.

Integration (any agent / surface):

    from src.governance.decision_record import record, cheaper_alternatives

    routing  = router.route_with_evidence(task)        # RoutingDecision
    bylaw    = engine.evaluate(task, action_type=...)  # BylawResult
    evidence = assess(results, high_stakes, reversible) # Assessment (optional)

    rec = record(
        action=task, project="myproject",
        routing=routing, bylaw=bylaw, evidence=evidence,
        alternatives=cheaper_alternatives(routing.provider, MODEL_COSTS),
        authorized_by="trust:autonomous",
    )
    print(rec.render())     # the human-readable record; already logged to disk
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Disposition(str, Enum):
    PROCEED = "proceed"       # acted (or cleared to act)
    REFUSED = "refused"       # bylaw block -- never executed
    ESCALATED = "escalated"   # handed to a human for decision
    CONTESTED = "contested"   # trusted sources disagree -- resolve first


def _val(x: Any) -> Any:
    """Unwrap an Enum to its .value; pass through everything else. Lets this
    module accept real BylawAction/Verdict enums or plain strings equally."""
    return x.value if isinstance(x, Enum) else x


def cheaper_alternatives(chosen: str, costs: dict[str, float]) -> list[dict]:
    """Providers strictly cheaper than the chosen one, with an honest note.

    The cost-first router picks the cheapest *capable* provider, so any cheaper
    provider that was not chosen was, by definition, not selected by capability
    routing. That is a true statement about the router's contract -- not a guess
    about the specific task -- so it is safe to record.
    """
    chosen_cost = costs.get(chosen)
    if chosen_cost is None:
        return []
    out = []
    for name, c in sorted(costs.items(), key=lambda kv: kv[1]):
        if c < chosen_cost:
            out.append({"provider": name, "cost_per_1k": c,
                        "why_not": "cheaper tier not selected by capability routing"})
    return out


@dataclass
class DecisionRecord:
    action: str
    disposition: Disposition
    rationale: str
    project: str | None = None
    chosen_provider: str | None = None
    category: str | None = None
    confidence: float | None = None
    estimated_cost: float | None = None
    route_reason: str | None = None
    alternatives: list[dict] = field(default_factory=list)
    bylaw_action: str | None = None
    bylaw_reason: str | None = None
    evidence: dict | None = None
    authorized_by: str | None = None
    ts: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_entry(self) -> dict:
        return {
            "ts": self.ts,
            "action": self.action,
            "project": self.project,
            "disposition": self.disposition.value,
            "rationale": self.rationale,
            "chosen_provider": self.chosen_provider,
            "category": self.category,
            "confidence": self.confidence,
            "estimated_cost_usd": self.estimated_cost,   # task/plan total, not per-1k
            "route_reason": self.route_reason,
            "alternatives_considered": self.alternatives,
            "bylaw_action": self.bylaw_action,
            "bylaw_reason": self.bylaw_reason,
            "evidence": self.evidence,
            "authorized_by": self.authorized_by,
        }

    def render(self) -> str:
        """Plain-language record -- the artifact a human/auditor reads."""
        icon = {"proceed": "✓", "refused": "✗", "escalated": "⤴", "contested": "⚠"}
        lines = [
            f"DECISION RECORD  [{icon.get(self.disposition.value, '·')} "
            f"{self.disposition.value.upper()}]"
            + (f"  ·  {self.project}" if self.project else ""),
            f"  when:   {self.ts}",
            f"  action: {self.action}",
            f"  why:    {self.rationale}",
        ]
        if self.chosen_provider is not None:
            cost = f" (~${self.estimated_cost}/1k)" if self.estimated_cost is not None else ""
            conf = f", confidence {self.confidence}" if self.confidence is not None else ""
            lines.append(f"  routed: {self.chosen_provider}{cost}{conf}")
            if self.route_reason:
                lines.append(f"          reason: {self.route_reason}")
        if self.alternatives:
            passed = ", ".join(
                f"{a.get('provider')} (${a.get('cost_per_1k')}/1k)" for a in self.alternatives
            )
            lines.append(f"  passed over (cheaper, not capability-selected): {passed}")
        if self.bylaw_action is not None:
            lines.append(f"  bylaws: {self.bylaw_action}"
                         + (f" — {self.bylaw_reason}" if self.bylaw_reason else ""))
        if self.evidence is not None:
            e = self.evidence
            lines.append(f"  evidence: {e.get('verdict')} (score {e.get('score')})"
                         + (f" — {e.get('reason')}" if e.get('reason') else ""))
        if self.authorized_by is not None:
            lines.append(f"  authorized by: {self.authorized_by}")
        return "\n".join(lines)


def _disposition(bylaw_action: Any, evidence: dict | None) -> Disposition:
    """Derive the final disposition deterministically from upstream results.
    Order matters: a hard block wins over everything; a genuine source conflict
    is surfaced before generic escalation."""
    ba = _val(bylaw_action)
    if ba == "block":
        return Disposition.REFUSED
    if evidence and _val(evidence.get("verdict")) == "contested":
        return Disposition.CONTESTED
    if ba == "escalate" or (evidence and evidence.get("require_human")):
        return Disposition.ESCALATED
    return Disposition.PROCEED


def compose(
    action: str,
    routing: Any = None,
    bylaw: Any = None,
    evidence: Any = None,
    alternatives: list[dict] | None = None,
    authorized_by: str | None = None,
    project: str | None = None,
) -> DecisionRecord:
    """Build a DecisionRecord from real upstream objects (duck-typed).

    routing:  anything with .provider/.category/.confidence/.estimated_cost/.reason
              (e.g. router.RoutingDecision) -- or None.
    bylaw:    anything with .action (enum or str) and .reason (e.g. BylawResult).
    evidence: anything with .verdict/.score/.require_human/.reason
              (e.g. research_quality.Assessment) -- or None.
    """
    ev_dict = None
    if evidence is not None:
        ev_dict = {
            "verdict": _val(getattr(evidence, "verdict", None)),
            "score": getattr(evidence, "score", None),
            "require_human": getattr(evidence, "require_human", None),
            "reason": getattr(evidence, "reason", None),
        }

    bylaw_action = getattr(bylaw, "action", None) if bylaw is not None else None
    disp = _disposition(bylaw_action, ev_dict)

    reason_bits = []
    if disp is Disposition.REFUSED:
        reason_bits.append(getattr(bylaw, "reason", "blocked by bylaws"))
    elif disp is Disposition.CONTESTED:
        reason_bits.append(ev_dict.get("reason") or "trusted sources disagree")
    elif disp is Disposition.ESCALATED:
        reason_bits.append(
            getattr(bylaw, "reason", None) if _val(bylaw_action) == "escalate"
            else (ev_dict or {}).get("reason") or "requires human decision")
    else:
        reason_bits.append(getattr(routing, "reason", None) or "cleared to proceed")
    rationale = "; ".join(b for b in reason_bits if b)

    return DecisionRecord(
        action=action,
        disposition=disp,
        rationale=rationale,
        project=project,
        chosen_provider=getattr(routing, "provider", None),
        category=_val(getattr(routing, "category", None)),
        confidence=getattr(routing, "confidence", None),
        estimated_cost=getattr(routing, "estimated_cost", None),
        route_reason=getattr(routing, "reason", None),
        alternatives=alternatives or [],
        bylaw_action=_val(bylaw_action),
        bylaw_reason=getattr(bylaw, "reason", None) if bylaw is not None else None,
        evidence=ev_dict,
        authorized_by=authorized_by,
    )


def record(action: str, **kwargs: Any) -> DecisionRecord:
    """Compose AND persist a decision record. Never raises: if logging fails the
    record is still returned so the caller's flow is never broken by an audit
    write. Returns the DecisionRecord (already rendered-able)."""
    rec = compose(action, **kwargs)
    try:
        from src.utils.logging import write_jsonl
        write_jsonl("decisions.jsonl", rec.to_entry())
    except Exception:
        pass
    return rec


if __name__ == "__main__":
    # Demo: what a cloner sees immediately -- one record per disposition.
    class _R:  # stand-in for RoutingDecision
        provider, category, confidence, estimated_cost = "ollama", "research", 0.82, 0.0
        reason = "local model capable; cheapest tier"

    class _B:
        def __init__(self, a, r):
            self.action, self.reason = a, r

    class _E:
        def __init__(self, v, s, h, r):
            self.verdict, self.score, self.require_human, self.reason = v, s, h, r

    costs = {"ollama": 0.0, "perplexity": 0.001, "grok": 0.002, "claude-opus": 0.015}
    demos = [
        compose("summarize competitor reviews", routing=_R(),
                bylaw=_B("proceed", "safe read-only"),
                evidence=_E("sufficient", 0.86, False, "corroborated"),
                alternatives=cheaper_alternatives("perplexity", costs),
                authorized_by="trust:autonomous", project="demo"),
        compose("rm -rf build/", bylaw=_B("block", "destructive path outside attic"),
                project="demo"),
        compose("publish pricing page", bylaw=_B("escalate", "irreversible external"),
                evidence=_E("sufficient", 0.7, True, "reversible-high-stakes"),
                project="demo"),
        compose("is ingredient X safe", routing=_R(),
                bylaw=_B("proceed", "read-only"),
                evidence=_E("contested", 0.8, True,
                            "perplexity and grok share the topic but assert opposite conclusions"),
                project="demo"),
    ]
    for d in demos:
        print(d.render())
        print("-" * 72)
