"""Legal Research Advisor — Repo Steward pattern applied to law.

A governed ADVISOR for a licensed attorney. Not legal advice to the public
(UPL firewall). Public-record sources only (CourtListener / Free Law Project).
It advises; it never files, serves, or sends.

Composes existing primitives:

  * observe.adapters.courtlistener  -- public-record opinion search
  * execution.research              -- optional free-first web layer
  * execution.router.LLMRouter      -- local-first route_with_evidence
  * research_quality.assess         -- SUFFICIENT / WEAK / CONTESTED / INSUFFICIENT
  * autonomy.classify_action_risk / decide / must_stop
  * decision_record.record(authorized_by="agent:legal_research")

CITE-OR-REFUSE (core): every asserted holding must carry a verified
CourtListener opinion URL. Claims without a verifiable citation are DROPPED,
never stated.

CLI:
  python -m src.agents.legal_research_agent "qualified immunity summary judgment"
  make agent-legal Q="..."

Orchestrator:
  python -m src.main --agent legal_research
"""

from __future__ import annotations

import argparse
import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from ..governance.bylaws import get_bylaw_engine, AgentRole, BylawAction
from ..governance.persona import render_persona_block
from ..observe.adapters.courtlistener import (
    OPINION_URL_RE,
    parse_payload,
    search_opinions,
    to_research_results,
)


# ── Framing / UPL firewall ────────────────────────────────────────────────────

DISCLAIMER = (
    "Research aid for a licensed attorney. Not legal advice. Verify before filing."
)

# Phrases that indicate a non-attorney consumer seeking advice (UPL risk).
_PUBLIC_ADVICE_PATTERNS = (
    r"\b(i\s+want\s+to\s+sue|should\s+i\s+sue|can\s+i\s+sue)\b",
    r"\b(what\s+should\s+i\s+do\s+about\s+my\s+(case|lawsuit|divorce|arrest))\b",
    r"\b(am\s+i\s+going\s+to\s+jail|will\s+i\s+win\s+my\s+case)\b",
    r"\b(draft\s+me\s+a\s+(lawsuit|complaint|will)\s+to\s+file)\b",
    r"\b(i\s+am\s+not\s+(a\s+)?lawyer|i'?m\s+not\s+(an?\s+)?attorney)\b",
    r"\b(advise\s+me|give\s+me\s+legal\s+advice)\b",
    r"\b(for\s+the\s+public|general\s+public\s+advice)\b",
)

# Attorney-tool framing that clears the UPL gate for research.
_ATTORNEY_FRAMING = (
    r"\b(for\s+(my\s+)?(client|matter)|as\s+counsel|attorney\s+research)\b",
    r"\b(licensed\s+attorney|for\s+a\s+lawyer|counsel\s+memo)\b",
    r"\b(research\s+(memo|brief)|case\s+law\s+(research|survey))\b",
    r"\b(matter\s+summary|issue\s+spotting)\b",
)

# Proposed side-effect actions that must escalate (never auto-run).
_SIDE_EFFECT_ACTIONS = (
    "file a motion in the pending matter",
    "advise a client to settle immediately",
    "send a demand letter to opposing counsel",
)


def is_public_advice_request(text: str) -> bool:
    """True when the query looks like consumer legal advice (UPL risk)."""
    t = (text or "").lower()
    if not t.strip():
        return False
    for pat in _PUBLIC_ADVICE_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            return True
    return False


def has_attorney_framing(text: str) -> bool:
    t = (text or "").lower()
    for pat in _ATTORNEY_FRAMING:
        if re.search(pat, t, re.IGNORECASE):
            return True
    return False


def upl_blocks(text: str, *, attorney_confirmed: bool = False) -> bool:
    """Refuse when public-advice request and no attorney framing/confirmation."""
    if attorney_confirmed:
        return False
    if is_public_advice_request(text) and not has_attorney_framing(text):
        return True
    return False


# ── Cite-or-refuse ────────────────────────────────────────────────────────────

@dataclass
class Authority:
    case_name: str
    holding: str
    url: str
    citation: str = ""
    court: str = ""
    date_filed: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_name": self.case_name,
            "holding": self.holding,
            "url": self.url,
            "citation": self.citation,
            "court": self.court,
            "date_filed": self.date_filed,
        }


def _citation_from_provenance(prov: list[str]) -> str:
    for p in prov or []:
        if isinstance(p, str) and p.startswith("citation:"):
            return p[len("citation:"):]
    return ""


def authorities_from_events(events: list[Any]) -> list[Authority]:
    """Build Authority rows from CourtListener ObserveEvents (pre-filter)."""
    out: list[Authority] = []
    for e in events or []:
        url = getattr(e, "url", "") or ""
        title = getattr(e, "title", "") or ""
        summary = getattr(e, "summary", "") or ""
        # Holding text: prefer snippet portion after last period block
        holding = summary
        if ". " in summary:
            # Keep court/cite head + rest as holding material
            holding = summary
        cite = _citation_from_provenance(getattr(e, "provenance", []) or [])
        out.append(Authority(
            case_name=title,
            holding=holding[:500] if holding else title,
            url=url,
            citation=cite,
        ))
    return out


def cite_or_refuse(
    claims: list[Authority | dict],
) -> tuple[list[Authority], list[dict]]:
    """Keep only claims with a verified CourtListener opinion URL.

    Claims without a verifiable citation are DROPPED (returned in dropped list),
    never stated as holdings. Pure; no network.
    """
    kept: list[Authority] = []
    dropped: list[dict] = []
    for c in claims or []:
        if isinstance(c, Authority):
            name, holding, url = c.case_name, c.holding, c.url
            extra = c.as_dict()
        else:
            name = str(c.get("case_name") or c.get("claim") or "")
            holding = str(c.get("holding") or c.get("text") or "")
            url = str(c.get("url") or "")
            extra = dict(c)
        url_ok = bool(url and OPINION_URL_RE.match(url.split("?")[0]))
        if url_ok and (holding or name):
            if isinstance(c, Authority):
                kept.append(c)
            else:
                kept.append(Authority(
                    case_name=name,
                    holding=holding or name,
                    url=url.split("?")[0],
                    citation=str(c.get("citation") or ""),
                    court=str(c.get("court") or ""),
                    date_filed=str(c.get("date_filed") or ""),
                ))
        else:
            extra["drop_reason"] = (
                "no verified CourtListener opinion URL"
                if not url_ok else "empty holding"
            )
            dropped.append(extra)
    return kept, dropped


# ── Briefing ──────────────────────────────────────────────────────────────────

@dataclass
class LegalBriefing:
    question: str
    status: str  # done | refused_upl | escalate | blocked | error
    authorities: list[Authority] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)
    confidence: float | None = None
    evidence_verdict: str | None = None
    evidence_reason: str | None = None
    contested: bool = False
    autonomy_gate: str | None = None
    autonomy_reason: str | None = None
    decision_disposition: str | None = None
    needs_attorney: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    route_provider: str | None = None
    sources_note: str = (
        "Public-record sources only (CourtListener / Free Law Project). "
        "No Westlaw, Lexis, or other paid databases are queried."
    )

    def render(self) -> str:
        lines = [
            "LEGAL RESEARCH BRIEFING",
            f"  {DISCLAIMER}",
            "=" * 64,
            f"  status:     {self.status}",
            f"  decision:   {self.decision_disposition or 'n/a'}",
            f"  evidence:   {self.evidence_verdict or 'n/a'}"
            + (f" (score {self.confidence})" if self.confidence is not None else ""),
            f"  autonomy:   {self.autonomy_gate or 'n/a'}",
            f"  routed:     {self.route_provider or 'n/a'}",
            "",
            "ISSUE",
            "-" * 64,
            f"  {self.question}",
            "",
            "AUTHORITIES (cite-or-refuse: verified CourtListener URLs only)",
            "-" * 64,
        ]
        if not self.authorities:
            lines.append("  (none — insufficient cited public-record authority)")
        for i, a in enumerate(self.authorities, 1):
            lines.append(f"  {i}. {a.case_name}")
            if a.citation:
                lines.append(f"     citation: {a.citation}")
            lines.append(f"     holding:  {a.holding[:280]}")
            lines.append(f"     source:   {a.url}")
            lines.append("")

        if self.dropped:
            lines.append("DROPPED (no verifiable citation — not stated as holdings)")
            lines.append("-" * 64)
            for d in self.dropped[:8]:
                claim = d.get("case_name") or d.get("claim") or d.get("holding") or "?"
                lines.append(f"  ✗ {str(claim)[:100]}  [{d.get('drop_reason', 'uncited')}]")
            lines.append("")

        if self.contested or (self.evidence_verdict == "contested"):
            lines.append("CONTESTED AUTHORITY")
            lines.append("-" * 64)
            lines.append(
                f"  ⚠ {self.evidence_reason or 'Trusted sources disagree on this issue.'}"
            )
            lines.append("  Do not treat discordant authority as corroboration.")
            lines.append("")

        lines.append("NEEDS ATTORNEY JUDGMENT")
        lines.append("-" * 64)
        needs = list(self.needs_attorney)
        if not needs:
            needs = [
                "Confirm jurisdiction, procedural posture, and controlling circuit.",
                "Verify each citation against the full opinion text before relying.",
                "Apply professional judgment; this tool does not practice law.",
            ]
        for n in needs:
            lines.append(f"  • {n}")
        if self.autonomy_gate in ("escalate", "deny") or self.contested:
            lines.append(
                "  • Autonomy gate requires human decision before any filing "
                "or client-facing advice."
            )

        lines.append("")
        lines.append("SOURCES")
        lines.append("-" * 64)
        lines.append(f"  {self.sources_note}")
        if self.notes:
            for n in self.notes:
                lines.append(f"  • {n}")

        lines.append("")
        lines.append(
            "This agent does NOT file, serve, send, or advise clients. "
            "Advisor-to-attorney only."
        )
        lines.append(f"  {DISCLAIMER}")
        lines.append("=" * 64)
        return "\n".join(lines)


class LegalResearchAgent:
    """Governed legal-research advisor (public-record, attorney-tool only)."""

    def __init__(self, project_key: str | None = None):
        self.project_key = project_key
        self.bylaws = get_bylaw_engine(AgentRole.ANALYST)

    def build_prompt(self, task: str) -> str:
        persona_block = render_persona_block(self.project_key)
        return f"{persona_block}\n\n---\n\n{DISCLAIMER}\n\nTASK: {task}"

    async def run_once(
        self,
        task: str,
        *,
        attorney_confirmed: bool = False,
        events: list[Any] | None = None,
        fixture_payload: dict | None = None,
        extra_claims: list[Authority | dict] | None = None,
        search_fn: Callable[..., list] | None = None,
        skip_free_research: bool = False,
    ) -> dict:
        """One research cycle. Never raises into the orchestrator."""
        try:
            return await self._run_once_inner(
                task,
                attorney_confirmed=attorney_confirmed,
                events=events,
                fixture_payload=fixture_payload,
                extra_claims=extra_claims,
                search_fn=search_fn,
                skip_free_research=skip_free_research,
            )
        except Exception as exc:  # noqa: BLE001
            briefing = LegalBriefing(
                question=task,
                status="error",
                notes=[f"legal_research failed safe: {exc}"],
                needs_attorney=["Tool error — fall back to manual public-record research."],
            )
            return {
                "status": "error",
                "reason": str(exc),
                "evidence": {
                    "task": task,
                    "report": briefing.render(),
                    "provider": "local",
                    "cost": 0.0,
                    "auto_file": False,
                },
            }

    async def _run_once_inner(
        self,
        task: str,
        *,
        attorney_confirmed: bool,
        events: list[Any] | None,
        fixture_payload: dict | None,
        extra_claims: list[Authority | dict] | None,
        search_fn: Callable[..., list] | None,
        skip_free_research: bool,
    ) -> dict:
        notes: list[str] = [
            "Mode: governed advisor — never files, serves, or sends.",
            "Public record only; paid legal DBs are out of scope.",
        ]
        question = (task or "").strip()

        # ── UPL firewall ──────────────────────────────────────────────────
        if upl_blocks(question, attorney_confirmed=attorney_confirmed):
            briefing = LegalBriefing(
                question=question,
                status="refused_upl",
                needs_attorney=[
                    "This query reads as a request for legal advice to a "
                    "non-attorney end-user. Re-run as attorney research "
                    "(e.g. 'case law research for counsel: …') or set "
                    "attorney_confirmed=True in a private deployment.",
                ],
                notes=notes + ["UPL firewall: refused public-facing advice request."],
            )
            rec_disp = self._record(
                action=f"legal_research UPL refuse: {question[:120]}",
                bylaw_action=BylawAction.BLOCK,
                bylaw_reason="UPL firewall: non-attorney advice request",
                evidence_verdict="insufficient",
                evidence_require_human=True,
                evidence_reason="refused: unauthorized practice of law risk",
                route_provider="local",
                route_reason="UPL refuse — no research run",
            )
            briefing.decision_disposition = rec_disp
            text = briefing.render()
            return {
                "status": "refused_upl",
                "reason": "UPL firewall",
                "evidence": {
                    "task": question,
                    "report": text,
                    "authorities": [],
                    "dropped": [],
                    "decision_disposition": rec_disp,
                    "upl_refused": True,
                    "provider": "local",
                    "cost": 0.0,
                    "auto_file": False,
                    "disclaimer": DISCLAIMER,
                },
            }

        # ── Bylaw wrap ────────────────────────────────────────────────────
        bylaw_result = self.bylaws.evaluate(command=question, action_type="api_call")
        if bylaw_result.action == BylawAction.BLOCK:
            return {"status": "blocked", "reason": bylaw_result.reason}

        # ── Route (local-first; evidence only — briefing is deterministic) ─
        route_provider = "ollama"
        route_reason = "default local-first"
        route_obj: Any = None
        try:
            from ..execution.router import LLMRouter
            router = LLMRouter()
            decision = router.route_with_evidence(
                f"legal research (public record): {question[:200]}"
            )
            route_provider = decision.provider
            route_reason = decision.reason
            route_obj = decision
            notes.append(f"Router: {route_provider} — {route_reason[:120]}")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"router unavailable, staying local: {exc}")

        # ── Gather public-record opinions ─────────────────────────────────
        cl_events: list[Any] = []
        if events is not None:
            cl_events = list(events)
            notes.append(f"Using injected events ({len(cl_events)}).")
        elif fixture_payload is not None:
            cl_events = parse_payload(fixture_payload, query=question)
            notes.append(f"Using fixture payload ({len(cl_events)} opinions).")
        else:
            fn = search_fn or search_opinions
            try:
                cl_events = list(fn(question, max_results=8) or [])
            except Exception as exc:  # noqa: BLE001
                notes.append(f"CourtListener search failed safe: {exc}")
                cl_events = []
            if not cl_events:
                notes.append(
                    "CourtListener returned no results (network, auth, or empty). "
                    "Degrading to insufficient sources."
                )

        # Optional free research layer (no paid keys required; never required)
        free_results: list[dict] = []
        if not skip_free_research and events is None and fixture_payload is None:
            try:
                from ..execution.research import research as free_research
                r = free_research(
                    question, tier="analyst", high_stakes=True,
                    condense=True, allow_human=False,
                )
                if r.get("ok") and r.get("content"):
                    free_results.append({
                        "provider": r.get("provider") or "duckduckgo",
                        "content": str(r.get("content"))[:1200],
                        "urls": r.get("urls") or [],
                        "ts": "",
                    })
                    notes.append(f"Free research: provider={r.get('provider')}")
            except Exception as exc:  # noqa: BLE001
                notes.append(f"free research skipped: {exc}")

        # ── Build claims + cite-or-refuse ─────────────────────────────────
        raw_authorities = authorities_from_events(cl_events)
        if extra_claims:
            raw_authorities.extend(
                c if isinstance(c, Authority) else Authority(
                    case_name=str(c.get("case_name") or c.get("claim") or "claim"),
                    holding=str(c.get("holding") or c.get("text") or ""),
                    url=str(c.get("url") or ""),
                    citation=str(c.get("citation") or ""),
                )
                for c in extra_claims
            )
        kept, dropped = cite_or_refuse(raw_authorities)
        if dropped:
            notes.append(
                f"Cite-or-refuse dropped {len(dropped)} uncited claim(s)."
            )

        # ── research_quality.assess ───────────────────────────────────────
        research_rows = to_research_results(cl_events) if cl_events else []
        # Only rows that survived cite-or-refuse contribute to assess inputs
        kept_urls = {a.url for a in kept}
        research_rows = [
            r for r in research_rows
            if any(u in kept_urls for u in (r.get("urls") or []))
        ]
        research_rows.extend(free_results)

        from ..governance.research_quality import assess, Verdict

        # Irreversible=True for assess: relying on case authority to ground a
        # legal position is treated as high-stakes irreversible use of evidence,
        # so split/contradictory sources yield CONTESTED (not averaged away).
        assessment = assess(
            research_rows,
            high_stakes=True,
            reversible=False,
        )
        contested = assessment.verdict is Verdict.CONTESTED
        thin = assessment.verdict in (Verdict.INSUFFICIENT, Verdict.WEAK) or not kept

        # ── Autonomy on research vs side-effect proposals ─────────────────
        from ..governance.autonomy import (
            classify_action_risk,
            decide,
            must_stop,
        )
        from ..governance.trust import get_trust_manager, TrustLevel

        try:
            trust = get_trust_manager().get_trust_level("legal_research")
        except Exception:  # noqa: BLE001
            trust = TrustLevel.TRUSTED

        research_action = f"research public case law and brief counsel: {question[:80]}"
        risk = classify_action_risk(research_action, bylaw_result=bylaw_result)
        auto = decide(
            risk=risk,
            trust=trust,
            bylaw_action=bylaw_result.action,
            evidence_verdict=assessment.verdict,
            evidence_require_human=assessment.require_human or contested or thin,
        )

        # Side-effect proposals always must_stop
        side_escalations: list[str] = []
        for act in _SIDE_EFFECT_ACTIONS:
            r = classify_action_risk(act)
            d = decide(risk=r, trust=trust)
            if must_stop(d):
                side_escalations.append(f"{act} → gate={d.gate.value} risk={r}")

        # If research itself must_stop (contested / insufficient), status escalate
        status = "done"
        if must_stop(auto) or contested or thin:
            status = "escalate"
            notes.append(
                f"Autonomy/evidence requires attorney review: gate={auto.gate.value}, "
                f"verdict={assessment.verdict.value}"
            )

        needs = [
            "Confirm jurisdiction, procedural posture, and controlling authority.",
            "Read the full opinion text at each CourtListener URL before relying.",
            "This tool does not practice law and does not create an attorney-client "
            "relationship with any third party.",
        ]
        if contested:
            needs.insert(0, "Resolve CONTESTED authority before any filing posture.")
        if thin or not kept:
            needs.insert(0, "Insufficient cited sources — expand research or use premium "
                            "tools in your private layer, then re-run.")
        if side_escalations:
            needs.append(
                "Any FILE / SEND / ADVISE-CLIENT action is escalated; human only."
            )

        # ── Decision record (one per run) ─────────────────────────────────
        rec_disp = self._record(
            action=f"legal_research: {question[:160]}",
            bylaw_action=(
                BylawAction.ESCALATE if status == "escalate"
                else bylaw_result.action
            ),
            bylaw_reason=(
                assessment.reason if status == "escalate"
                else getattr(bylaw_result, "reason", "research proceed")
            ),
            evidence_verdict=assessment.verdict.value,
            evidence_require_human=assessment.require_human or contested or thin,
            evidence_reason=assessment.reason,
            evidence_score=assessment.score,
            route_provider=route_provider,
            route_reason=route_reason,
            route_obj=route_obj,
        )

        briefing = LegalBriefing(
            question=question,
            status=status,
            authorities=kept,
            dropped=dropped,
            confidence=assessment.score,
            evidence_verdict=assessment.verdict.value,
            evidence_reason=assessment.reason,
            contested=contested,
            autonomy_gate=auto.gate.value,
            autonomy_reason=auto.reason,
            decision_disposition=rec_disp,
            needs_attorney=needs,
            notes=notes + (
                ["Side-effect gates:"] + [f"  {s}" for s in side_escalations]
                if side_escalations else []
            ),
            route_provider=route_provider,
        )
        text = briefing.render()

        return {
            "status": status,
            "evidence": {
                "task": question,
                "report": text,
                "authorities": [a.as_dict() for a in kept],
                "dropped": dropped,
                "evidence_verdict": assessment.verdict.value,
                "evidence_score": assessment.score,
                "contested": contested,
                "autonomy_gate": auto.gate.value,
                "decision_disposition": rec_disp,
                "side_effect_escalations": side_escalations,
                "provider": route_provider,
                "cost": 0.0,
                "auto_file": False,
                "upl_refused": False,
                "disclaimer": DISCLAIMER,
                "public_record_only": True,
            },
        }

    def _record(
        self,
        *,
        action: str,
        bylaw_action: Any,
        bylaw_reason: str,
        evidence_verdict: str,
        evidence_require_human: bool,
        evidence_reason: str,
        evidence_score: float = 0.0,
        route_provider: str = "local",
        route_reason: str = "",
        route_obj: Any = None,
    ) -> str | None:
        try:
            from ..governance.decision_record import record as _record

            class _B:
                def __init__(self, a, r):
                    self.action, self.reason = a, r

            class _E:
                def __init__(self):
                    self.verdict = evidence_verdict
                    self.score = evidence_score
                    self.require_human = evidence_require_human
                    self.reason = evidence_reason

            routing = route_obj
            if routing is None:
                class _R:
                    provider = route_provider
                    category = "legal_research"
                    confidence = 0.7
                    estimated_cost = 0.0
                    reason = route_reason or "legal research advisor"
                routing = _R()

            rec = _record(
                action=action[:200],
                routing=routing,
                bylaw=_B(bylaw_action, bylaw_reason),
                evidence=_E(),
                authorized_by="agent:legal_research",
                project=self.project_key,
            )
            return getattr(getattr(rec, "disposition", None), "value", None)
        except Exception:
            return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Legal Research Advisor — public-record briefing for a licensed "
            "attorney. Not legal advice. Never files."
        ),
    )
    parser.add_argument(
        "question",
        nargs="*",
        help="Legal question or matter summary (text only; no confidential data)",
    )
    parser.add_argument(
        "--attorney-confirmed",
        action="store_true",
        help="Caller affirms this is for a licensed attorney (private deployments)",
    )
    parser.add_argument(
        "--fixture",
        default=None,
        help="Path to CourtListener search JSON fixture (network-free)",
    )
    args = parser.parse_args(argv)
    question = " ".join(args.question).strip()
    if not question:
        print(
            "Usage: python -m src.agents.legal_research_agent "
            "\"case law research for counsel: <issue>\""
        )
        print(f"\n{DISCLAIMER}")
        return 2

    fixture_payload = None
    if args.fixture:
        import json
        from pathlib import Path
        fixture_payload = json.loads(Path(args.fixture).read_text(encoding="utf-8"))

    agent = LegalResearchAgent()
    result = asyncio.run(agent.run_once(
        question,
        attorney_confirmed=args.attorney_confirmed,
        fixture_payload=fixture_payload,
        skip_free_research=bool(fixture_payload),
    ))
    report = (result.get("evidence") or {}).get("report") or result.get("reason") or ""
    print(report)
    status = result.get("status")
    return 0 if status in (
        "done", "escalate", "blocked", "refused_upl",
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
