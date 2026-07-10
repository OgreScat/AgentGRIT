"""Legal Research Advisor — UPL firewall, cite-or-refuse, CONTESTED, decision_record.

All tests are network-free (fixture payloads / injected events).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.legal_research_agent import (
    DISCLAIMER,
    Authority,
    LegalResearchAgent,
    cite_or_refuse,
    is_public_advice_request,
    upl_blocks,
)
from src.observe.adapters.courtlistener import (
    OPINION_URL_RE,
    parse_payload,
    to_research_results,
)
from src.governance.autonomy import classify_action_risk, decide, must_stop
from src.governance.research_quality import assess, Verdict

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "legal"
CL_FIXTURE = FIXTURES / "courtlistener_search.json"


def _fixture_payload() -> dict:
    return json.loads(CL_FIXTURE.read_text(encoding="utf-8"))


def test_parse_payload_fixture_has_opinion_urls():
    events = parse_payload(_fixture_payload(), query="test")
    assert len(events) >= 2
    assert all(e.source_id == "courtlistener" for e in events)
    assert all(OPINION_URL_RE.match(e.url) for e in events)
    assert "courtlistener.com/opinion/" in events[0].url


def test_cite_or_refuse_drops_uncited_claim():
    """Core: a claim with no verifiable CourtListener URL is DROPPED."""
    good = Authority(
        case_name="Pearson v. Callahan",
        holding="Qualified immunity protects officials when the right is not clearly established.",
        url="https://www.courtlistener.com/opinion/9434877/pearson-v-callahan/",
        citation="555 U.S. 223",
    )
    bad = {
        "case_name": "Invented Holding Co. v. Nobody",
        "holding": "The sky is always green on Tuesdays per secret doctrine.",
        "url": "",  # no citation
    }
    also_bad = Authority(
        case_name="Fake v. Fake",
        holding="Something from a paid DB we never queried.",
        url="https://example.com/not-courtlistener/123",
    )
    kept, dropped = cite_or_refuse([good, bad, also_bad])
    assert len(kept) == 1
    assert kept[0].case_name == "Pearson v. Callahan"
    assert len(dropped) == 2
    assert all("no verified" in d.get("drop_reason", "") for d in dropped)


def test_upl_firewall_blocks_public_advice():
    assert is_public_advice_request("should I sue my neighbor")
    assert upl_blocks("I want to sue my employer, advise me")
    assert upl_blocks("I am not a lawyer — will I win my case")
    # Attorney framing clears
    assert not upl_blocks(
        "case law research for counsel: qualified immunity at summary judgment"
    )
    assert not upl_blocks(
        "should I sue", attorney_confirmed=True,
    )


def test_file_send_advise_client_must_stop():
    for act in (
        "file a motion in the pending matter",
        "advise a client to settle immediately",
        "send a demand letter to opposing counsel",
    ):
        risk = classify_action_risk(act)
        assert risk >= 30, act
        assert must_stop(decide(risk=risk, trust="autonomous")), act


def test_research_brief_is_low_risk():
    risk = classify_action_risk(
        "research public case law and brief counsel: qualified immunity"
    )
    assert risk < 30
    assert not must_stop(decide(risk=risk, trust="trusted"))


def test_contested_on_split_authority_fixture():
    """Two high-trust courtlistener rows with opposite polarity → CONTESTED.

    Topic words must overlap enough for research_quality's Jaccard gate
    (same shape as tests/test_research_quality.py).
    """
    affirm = (
        "qualified immunity summary judgment doctrine confirmed effective "
        "supported proven verified studies clearly established"
    )
    deny = (
        "qualified immunity summary judgment doctrine refuted ineffective "
        "debunked unproven harmful contrary clearly established"
    )
    rows = [
        {
            "provider": "courtlistener",
            "content": affirm,
            "urls": ["https://www.courtlistener.com/opinion/111/a/"],
            "ts": "2024-01-01T00:00:00",
        },
        {
            "provider": "courtlistener",
            "content": deny,
            "urls": ["https://www.courtlistener.com/opinion/222/b/"],
            "ts": "2024-01-01T00:00:00",
        },
    ]
    a = assess(rows, high_stakes=True, reversible=False)
    assert a.verdict is Verdict.CONTESTED
    assert a.require_human is True


@pytest.mark.asyncio
async def test_agent_fixture_run_writes_decision_record(monkeypatch):
    written: list[dict] = []

    def fake_write(name, entry, log_dir=None):
        written.append({"name": name, "entry": entry})
        return True

    monkeypatch.setattr("src.utils.logging.write_jsonl", fake_write)

    # Plant an uncited claim; must be dropped from authorities in the briefing
    uncited = {
        "case_name": "Ghost Precedent v. Vacuum",
        "holding": "Courts always grant this motion without analysis.",
        "url": "",
    }

    agent = LegalResearchAgent()
    result = await agent.run_once(
        task="case law research for counsel: qualified immunity at summary judgment",
        attorney_confirmed=True,
        fixture_payload=_fixture_payload(),
        extra_claims=[uncited],
        skip_free_research=True,
    )

    assert result["status"] in ("done", "escalate")
    ev = result["evidence"]
    assert ev["auto_file"] is False
    assert ev["public_record_only"] is True
    assert ev["upl_refused"] is False
    assert DISCLAIMER in ev["report"]
    assert "NEEDS ATTORNEY JUDGMENT" in ev["report"]
    assert "LEGAL RESEARCH BRIEFING" in ev["report"]

    # Cite-or-refuse: uncited claim not among stated authorities
    names = [a["case_name"] for a in ev["authorities"]]
    assert "Ghost Precedent v. Vacuum" not in names
    assert any("Ghost" in str(d.get("case_name", "")) for d in ev["dropped"])
    # Dropped section appears in rendered report
    assert "DROPPED" in ev["report"] or "Ghost" in ev["report"]

    # At least one real CourtListener citation in the briefing
    assert any(
        "courtlistener.com/opinion/" in a["url"] for a in ev["authorities"]
    )
    assert "courtlistener.com/opinion/" in ev["report"]

    # decision_record once
    legal_recs = [
        w for w in written
        if w["name"] == "decisions.jsonl"
        and w["entry"].get("authorized_by") == "agent:legal_research"
    ]
    assert len(legal_recs) == 1
    assert legal_recs[0]["entry"].get("disposition") in (
        "proceed", "escalated", "contested", "refused",
    )


@pytest.mark.asyncio
async def test_agent_upl_refusal(monkeypatch):
    written: list[dict] = []
    monkeypatch.setattr(
        "src.utils.logging.write_jsonl",
        lambda name, entry, log_dir=None: written.append(entry) or True,
    )
    agent = LegalResearchAgent()
    result = await agent.run_once(
        task="I am not a lawyer — should I sue my boss? advise me",
        skip_free_research=True,
    )
    assert result["status"] == "refused_upl"
    ev = result["evidence"]
    assert ev["upl_refused"] is True
    assert DISCLAIMER in ev["report"]
    assert ev["authorities"] == []
    assert any(
        e.get("authorized_by") == "agent:legal_research" for e in written
    )


@pytest.mark.asyncio
async def test_agent_contested_path(monkeypatch):
    written: list[dict] = []
    monkeypatch.setattr(
        "src.utils.logging.write_jsonl",
        lambda name, entry, log_dir=None: written.append(entry) or True,
    )

    # Shared topic tokens + opposite polarity (matches research_quality tests)
    affirm = (
        "qualified immunity summary judgment doctrine confirmed effective "
        "supported proven verified studies clearly established"
    )
    deny = (
        "qualified immunity summary judgment doctrine refuted ineffective "
        "debunked unproven harmful contrary clearly established"
    )
    from src.observe.schema import ObserveEvent
    from datetime import datetime, timezone
    now = datetime.now(tz=timezone.utc).isoformat()
    events = [
        ObserveEvent(
            event_id="cl:1", source_id="courtlistener", source_type="case_law",
            title="Affirming Case v. State",
            summary=affirm,
            category="legal_opinion", ts=now, first_seen_at=now,
            url="https://www.courtlistener.com/opinion/111111/affirming/",
            provenance=["https://www.courtlistener.com/opinion/111111/affirming/"],
        ),
        ObserveEvent(
            event_id="cl:2", source_id="courtlistener", source_type="case_law",
            title="Denying Case v. State",
            summary=deny,
            category="legal_opinion", ts=now, first_seen_at=now,
            url="https://www.courtlistener.com/opinion/222222/denying/",
            provenance=["https://www.courtlistener.com/opinion/222222/denying/"],
        ),
    ]

    agent = LegalResearchAgent()
    result = await agent.run_once(
        task="case law research for counsel: split on immunity doctrine",
        attorney_confirmed=True,
        events=events,
        skip_free_research=True,
    )
    ev = result["evidence"]
    assert ev["contested"] is True or ev["evidence_verdict"] == "contested"
    assert "CONTESTED" in ev["report"]
    assert "NEEDS ATTORNEY JUDGMENT" in ev["report"]
    assert result["status"] == "escalate"
    assert any(
        e.get("authorized_by") == "agent:legal_research" for e in written
    )


@pytest.mark.asyncio
async def test_adapter_fail_safe_empty_on_search_error(monkeypatch):
    """Network failures degrade; agent does not raise."""
    def boom(*a, **k):
        raise RuntimeError("network down")

    agent = LegalResearchAgent()
    result = await agent.run_once(
        task="case law research for counsel: remote work tax domicile",
        attorney_confirmed=True,
        search_fn=boom,
        skip_free_research=True,
    )
    assert result["status"] in ("escalate", "done", "error")
    assert result.get("evidence", {}).get("auto_file") is False
    report = (result.get("evidence") or {}).get("report") or ""
    assert DISCLAIMER in report


def test_to_research_results_provider_is_courtlistener():
    events = parse_payload(_fixture_payload())
    rows = to_research_results(events)
    assert rows
    assert all(r["provider"] == "courtlistener" for r in rows)
    assert all(r.get("urls") for r in rows)
