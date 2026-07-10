"""
GovernedBrief — normalized domain briefing for the read-only /brief UI.

Adapters map each agent result envelope → GovernedBrief. Profiles are data
(not code): a private deployment can pass legal labels without forking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.utils.logging import DEFAULT_LOG_DIR, read_jsonl_tail


# ── Profiles (data only — no domain strings in the generic default) ───────────

GENERIC_PROFILE: dict[str, str] = {
    "id": "generic",
    "title": "Governed brief",
    "judgment_label": "Needs human judgment",
    "disclaimer": (
        "Advisory only. Verify before acting. "
        "Not a substitute for professional judgment."
    ),
    "contested_label": "CONTESTED evidence",
}

# Sample override for docs/tests — not the default, not embedded in HTML.
LEGAL_PROFILE: dict[str, str] = {
    "id": "legal",
    "title": "Legal research briefing",
    "judgment_label": "Needs attorney judgment",
    "disclaimer": "Not legal advice. Verify before filing.",
    "contested_label": "CONTESTED authority",
}

_PROFILES: dict[str, dict[str, str]] = {
    "generic": GENERIC_PROFILE,
    "legal": LEGAL_PROFILE,
}


def get_profile(profile_id: str | None = None) -> dict[str, str]:
    """Return a copy of a named profile; unknown → generic."""
    pid = (profile_id or "generic").strip().lower() or "generic"
    base = _PROFILES.get(pid) or GENERIC_PROFILE
    return dict(base)


def register_profile(profile_id: str, profile: dict[str, str]) -> None:
    """Allow private layers to register additional profiles at runtime."""
    if not profile_id:
        return
    merged = dict(GENERIC_PROFILE)
    merged.update({k: str(v) for k, v in (profile or {}).items() if v is not None})
    merged["id"] = profile_id
    _PROFILES[profile_id.strip().lower()] = merged


# ── Confidence bands ──────────────────────────────────────────────────────────

def confidence_band(score: float | None, contested: bool = False) -> str:
    """Derive a human band from score + contested flag.

    Thresholds align with research_quality defaults:
      strong >= 0.82, adequate >= 0.62, else thin; contested → flagged.
    """
    if contested:
        return "flagged"
    if score is None:
        return "thin"
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "thin"
    if s >= 0.82:
        return "strong"
    if s >= 0.62:
        return "adequate"
    return "thin"


_URL_OK = re.compile(r"^https?://", re.I)


def _is_verified_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    if not _URL_OK.match(u):
        return False
    try:
        p = urlparse(u)
        return bool(p.netloc)
    except Exception:
        return False


# ── Schema ────────────────────────────────────────────────────────────────────

@dataclass
class AuthorityRef:
    title: str
    url: str
    citation: str = ""
    verified: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "citation": self.citation,
            "verified": bool(self.verified and _is_verified_url(self.url)),
        }


@dataclass
class GovernedBrief:
    kind: str
    question: str
    disposition: str
    evidence_verdict: str | None = None
    confidence_score: float | None = None
    confidence_band: str = "thin"
    authorities: list[AuthorityRef] = field(default_factory=list)
    dropped_count: int = 0
    contested: bool = False
    contested_reason: str = ""
    needs_judgment: list[str] = field(default_factory=list)
    autonomy_gate: str | None = None
    framing: str = ""
    ts: str = ""
    provider: str | None = None
    run_id: str | None = None
    status: str | None = None

    def verified_authorities(self) -> list[AuthorityRef]:
        return [
            a for a in self.authorities
            if a.verified and _is_verified_url(a.url)
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "question": self.question,
            "disposition": self.disposition,
            "evidence_verdict": self.evidence_verdict,
            "confidence_score": self.confidence_score,
            "confidence_band": self.confidence_band,
            "authorities": [a.as_dict() for a in self.verified_authorities()],
            "dropped_count": self.dropped_count,
            "contested": self.contested,
            "contested_reason": self.contested_reason,
            "needs_judgment": list(self.needs_judgment),
            "autonomy_gate": self.autonomy_gate,
            "framing": self.framing,
            "ts": self.ts or datetime.now().isoformat(),
            "provider": self.provider,
            "run_id": self.run_id,
            "status": self.status,
            "read_only": True,
        }


def brief_to_entry(brief: GovernedBrief, *, profile_id: str = "generic") -> dict[str, Any]:
    d = brief.to_dict()
    d["profile_id"] = profile_id
    d["id"] = brief.run_id or f"{brief.kind}:{d['ts']}"
    return d


def apply_profile(brief_dict: dict[str, Any], profile_id: str | None = None) -> dict[str, Any]:
    """Attach profile labels/disclaimer for the UI (does not mutate domain data)."""
    prof = get_profile(profile_id)
    out = dict(brief_dict)
    out["profile"] = prof
    out["read_only"] = True
    # UI never sees unverified authorities
    authorities = []
    for a in out.get("authorities") or []:
        if isinstance(a, dict) and a.get("verified") and _is_verified_url(str(a.get("url") or "")):
            authorities.append(a)
    out["authorities"] = authorities
    return out


# ── Adapters ──────────────────────────────────────────────────────────────────

def _ev(envelope: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        return {}
    ev = envelope.get("evidence")
    return ev if isinstance(ev, dict) else envelope


def adapt_legal_research(envelope: dict[str, Any]) -> GovernedBrief:
    ev = _ev(envelope)
    authorities: list[AuthorityRef] = []
    for a in ev.get("authorities") or []:
        if not isinstance(a, dict):
            continue
        url = str(a.get("url") or "")
        # Only cite-or-refuse survivors are in authorities; still re-verify URL
        verified = _is_verified_url(url)
        if not verified:
            continue
        authorities.append(AuthorityRef(
            title=str(a.get("case_name") or a.get("title") or "authority"),
            url=url.split("?")[0],
            citation=str(a.get("citation") or ""),
            verified=True,
        ))
    dropped = ev.get("dropped") or []
    contested = bool(ev.get("contested") or ev.get("evidence_verdict") == "contested")
    score = ev.get("evidence_score")
    if score is None:
        score = ev.get("confidence")
    try:
        score_f = float(score) if score is not None else None
    except (TypeError, ValueError):
        score_f = None
    disp = (
        ev.get("decision_disposition")
        or ("refused" if envelope.get("status") == "refused_upl" else None)
        or ("escalated" if envelope.get("status") == "escalate" else None)
        or ("proceed" if envelope.get("status") == "done" else "unknown")
    )
    needs = list(ev.get("needs_attorney") or ev.get("needs_judgment") or [])
    return GovernedBrief(
        kind="legal_research",
        question=str(ev.get("task") or envelope.get("question") or ""),
        disposition=str(disp),
        evidence_verdict=ev.get("evidence_verdict"),
        confidence_score=score_f,
        confidence_band=confidence_band(score_f, contested),
        authorities=authorities,
        dropped_count=len(dropped) if isinstance(dropped, list) else int(dropped or 0),
        contested=contested,
        contested_reason=str(ev.get("evidence_reason") or "") if contested else "",
        needs_judgment=needs,
        autonomy_gate=ev.get("autonomy_gate"),
        framing="",  # profile supplies disclaimer
        ts=str(ev.get("ts") or datetime.now().isoformat()),
        provider=ev.get("provider"),
        status=envelope.get("status"),
    )


def adapt_repo_steward(envelope: dict[str, Any]) -> GovernedBrief:
    ev = _ev(envelope)
    proposals = ev.get("proposals") or []
    needs: list[str] = []
    for p in proposals:
        if not isinstance(p, dict):
            continue
        action = str(p.get("action") or "")
        gate = str(p.get("gate") or "")
        esc = bool(p.get("escalated"))
        finding = p.get("finding") or {}
        path = finding.get("path") if isinstance(finding, dict) else ""
        label = f"[{gate}] {action}" if action else str(finding)
        if path:
            label = f"{path}: {label}"
        needs.append(label[:200])
        if esc and action:
            needs.append(f"ESCALATED remediation requires human approval: {action[:120]}")
    disp = ev.get("decision_disposition") or (
        "escalated" if any(
            isinstance(p, dict) and p.get("escalated") for p in proposals
        ) else "proceed"
    )
    # Steward does not emit clickable authorities (no external citations)
    return GovernedBrief(
        kind="repo_steward",
        question=str(ev.get("task") or ev.get("root") or "repo steward"),
        disposition=str(disp),
        evidence_verdict=None,
        confidence_score=1.0 if not needs else 0.7,
        confidence_band=confidence_band(1.0 if not needs else 0.7, False),
        authorities=[],
        dropped_count=0,
        contested=False,
        needs_judgment=needs or ["No findings — nothing to judge."],
        autonomy_gate="escalate" if disp == "escalated" else "allow",
        ts=str(ev.get("ts") or datetime.now().isoformat()),
        provider=ev.get("provider") or "local",
        status=envelope.get("status"),
    )


def adapt_observe(envelope: dict[str, Any]) -> GovernedBrief:
    """Map observe GateResult.to_dict() or /observe/view result block."""
    # Accept full GateResult dict or {result: {...}} wrapper
    data = envelope.get("result") if isinstance(envelope.get("result"), dict) else envelope
    events = data.get("events") or []
    authorities: list[AuthorityRef] = []
    needs: list[str] = []
    for e in events:
        if not isinstance(e, dict):
            continue
        url = str(e.get("url") or "")
        title = str(e.get("title") or "observation")
        actionable = bool(e.get("actionable"))
        if _is_verified_url(url) and actionable:
            authorities.append(AuthorityRef(
                title=title[:160],
                url=url,
                citation=str(e.get("source_id") or e.get("source") or ""),
                verified=True,
            ))
        else:
            why = []
            if e.get("freshness_grade") == "stale":
                why.append("stale")
            if not actionable:
                why.append("not actionable")
            if not _is_verified_url(url):
                why.append("no verified URL")
            needs.append(f"{title[:80]} — refused: {', '.join(why) or 'weak'}")
    verdict = data.get("assessment_verdict") or envelope.get("assessment_verdict")
    contested = verdict == "contested"
    score = data.get("assessment_score")
    try:
        score_f = float(score) if score is not None else None
    except (TypeError, ValueError):
        score_f = None
    disp = data.get("decision_disposition") or (
        "escalated" if data.get("actionable_count", 0) == 0 and events else "proceed"
    )
    return GovernedBrief(
        kind="observe",
        question=str(envelope.get("feed") or data.get("feed") or "observe run"),
        disposition=str(disp),
        evidence_verdict=str(verdict) if verdict else None,
        confidence_score=score_f,
        confidence_band=confidence_band(score_f, contested),
        authorities=authorities,
        dropped_count=int(data.get("non_actionable_count") or 0),
        contested=contested,
        contested_reason=str(data.get("assessment_reason") or "") if contested else "",
        needs_judgment=needs,
        autonomy_gate="escalate" if not authorities else "allow",
        ts=str(envelope.get("ts") or data.get("ts") or datetime.now().isoformat()),
        provider="observe",
        status="done",
    )


def adapt_decision_row(row: dict[str, Any]) -> GovernedBrief:
    """Best-effort brief from a decisions.jsonl row when briefs.jsonl is empty."""
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    contested = (evidence.get("verdict") == "contested") or (
        row.get("disposition") == "contested"
    )
    score = evidence.get("score")
    if score is None:
        score = row.get("confidence")
    try:
        score_f = float(score) if score is not None else None
    except (TypeError, ValueError):
        score_f = None
    return GovernedBrief(
        kind="decision",
        question=str(row.get("action") or ""),
        disposition=str(row.get("disposition") or "unknown"),
        evidence_verdict=evidence.get("verdict"),
        confidence_score=score_f,
        confidence_band=confidence_band(score_f, contested),
        authorities=[],
        dropped_count=0,
        contested=bool(contested),
        contested_reason=str(evidence.get("reason") or "") if contested else "",
        needs_judgment=[
            str(row.get("rationale") or "Review decision record for full context.")
        ],
        autonomy_gate=None,
        framing="",
        ts=str(row.get("ts") or ""),
        provider=row.get("chosen_provider"),
        status=row.get("disposition"),
        run_id=f"decision:{(row.get('ts') or '')}",
    )


def adapt_generic(envelope: dict[str, Any]) -> GovernedBrief:
    ev = _ev(envelope)
    return GovernedBrief(
        kind=str(envelope.get("kind") or ev.get("kind") or "generic"),
        question=str(ev.get("task") or envelope.get("question") or envelope.get("action") or ""),
        disposition=str(
            ev.get("decision_disposition")
            or envelope.get("disposition")
            or envelope.get("status")
            or "unknown"
        ),
        evidence_verdict=ev.get("evidence_verdict"),
        confidence_score=(
            float(ev["evidence_score"]) if ev.get("evidence_score") is not None
            else None
        ),
        confidence_band=confidence_band(
            float(ev["evidence_score"]) if ev.get("evidence_score") is not None else None,
            bool(ev.get("contested")),
        ),
        authorities=[],
        dropped_count=int(ev.get("dropped_count") or 0),
        contested=bool(ev.get("contested")),
        contested_reason=str(ev.get("evidence_reason") or ""),
        needs_judgment=list(ev.get("needs_judgment") or []),
        autonomy_gate=ev.get("autonomy_gate"),
        ts=str(ev.get("ts") or datetime.now().isoformat()),
        provider=ev.get("provider"),
        status=envelope.get("status"),
    )


def adapt_envelope(envelope: dict[str, Any], kind: str | None = None) -> GovernedBrief:
    """Dispatch to the right adapter by kind or envelope shape."""
    if not isinstance(envelope, dict):
        return adapt_generic({})
    # Already a stored brief entry
    if envelope.get("authorities") is not None and envelope.get("confidence_band"):
        return _from_stored(envelope)
    k = (kind or envelope.get("kind") or "").strip().lower()
    ev = _ev(envelope)
    if not k:
        if "authorities" in ev or envelope.get("status") == "refused_upl":
            k = "legal_research"
        elif "proposals" in ev:
            k = "repo_steward"
        elif "events" in envelope or "events" in ev or "assessment_verdict" in (
            envelope.get("result") or envelope
        ):
            k = "observe"
        elif "disposition" in envelope and "action" in envelope:
            k = "decision"
    if k in ("legal_research", "legal"):
        return adapt_legal_research(envelope)
    if k in ("repo_steward", "steward"):
        return adapt_repo_steward(envelope)
    if k == "observe":
        return adapt_observe(envelope)
    if k == "decision":
        return adapt_decision_row(envelope)
    return adapt_generic(envelope)


def _from_stored(entry: dict[str, Any]) -> GovernedBrief:
    authorities = []
    for a in entry.get("authorities") or []:
        if not isinstance(a, dict):
            continue
        url = str(a.get("url") or "")
        if not (a.get("verified") and _is_verified_url(url)):
            continue
        authorities.append(AuthorityRef(
            title=str(a.get("title") or ""),
            url=url,
            citation=str(a.get("citation") or ""),
            verified=True,
        ))
    contested = bool(entry.get("contested"))
    score = entry.get("confidence_score")
    try:
        score_f = float(score) if score is not None else None
    except (TypeError, ValueError):
        score_f = None
    return GovernedBrief(
        kind=str(entry.get("kind") or "generic"),
        question=str(entry.get("question") or ""),
        disposition=str(entry.get("disposition") or "unknown"),
        evidence_verdict=entry.get("evidence_verdict"),
        confidence_score=score_f,
        confidence_band=str(
            entry.get("confidence_band") or confidence_band(score_f, contested)
        ),
        authorities=authorities,
        dropped_count=int(entry.get("dropped_count") or 0),
        contested=contested,
        contested_reason=str(entry.get("contested_reason") or ""),
        needs_judgment=list(entry.get("needs_judgment") or []),
        autonomy_gate=entry.get("autonomy_gate"),
        framing=str(entry.get("framing") or ""),
        ts=str(entry.get("ts") or ""),
        provider=entry.get("provider"),
        run_id=entry.get("id") or entry.get("run_id"),
        status=entry.get("status"),
    )


# ── Load for UI ───────────────────────────────────────────────────────────────

def list_briefs(log_dir: Path | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Newest-first brief entries from logs/briefs.jsonl (or [])."""
    root = Path(log_dir) if log_dir is not None else DEFAULT_LOG_DIR
    rows = read_jsonl_tail("briefs.jsonl", n=max(limit, 1), log_dir=root)
    out = []
    for r in reversed(rows):
        if isinstance(r, dict):
            rid = r.get("id") or r.get("run_id") or r.get("ts")
            out.append({"id": rid, "ts": r.get("ts"), "kind": r.get("kind"),
                        "question": (r.get("question") or "")[:80],
                        "disposition": r.get("disposition")})
    return out


def load_brief(
    run: str = "latest",
    *,
    log_dir: Path | None = None,
    profile: str | None = "generic",
) -> dict[str, Any]:
    """Load one brief for GET /brief/data. Fail-safe empty shell."""
    root = Path(log_dir) if log_dir is not None else DEFAULT_LOG_DIR
    empty = apply_profile({
        "kind": "empty",
        "question": "",
        "disposition": "unknown",
        "confidence_band": "thin",
        "authorities": [],
        "dropped_count": 0,
        "contested": False,
        "needs_judgment": [],
        "empty": True,
        "message": "No briefs yet. Run an agent that calls record_brief, or wait for decisions.",
    }, profile)

    try:
        rows = read_jsonl_tail("briefs.jsonl", n=50, log_dir=root)
        chosen: dict[str, Any] | None = None
        if rows:
            if run in (None, "", "latest"):
                chosen = rows[-1]
            else:
                for r in reversed(rows):
                    rid = str(r.get("id") or r.get("run_id") or r.get("ts") or "")
                    if rid == run or (run in rid):
                        chosen = r
                        break
                if chosen is None:
                    chosen = rows[-1]
        if chosen is None:
            # Fallback: newest decision row
            decisions = read_jsonl_tail("decisions.jsonl", n=5, log_dir=root)
            if not decisions:
                return empty
            brief = adapt_decision_row(decisions[-1])
            return apply_profile(brief.to_dict(), profile)

        brief = adapt_envelope(chosen)
        d = brief.to_dict()
        d["id"] = chosen.get("id") or brief.run_id
        d["empty"] = False
        return apply_profile(d, profile)
    except Exception as exc:  # noqa: BLE001
        empty["message"] = f"brief load failed safe: {exc}"
        return empty
