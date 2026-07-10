"""Governed brief UI — adapters, profiles, verified-only citations, read-only routes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api.brief_data import (
    GENERIC_PROFILE,
    LEGAL_PROFILE,
    adapt_envelope,
    adapt_legal_research,
    adapt_repo_steward,
    adapt_observe,
    apply_profile,
    confidence_band,
    get_profile,
    load_brief,
    list_briefs,
)
from src.api.brief_page import BRIEF_HTML
from src.governance.brief_record import record_brief


def test_confidence_bands():
    assert confidence_band(0.9) == "strong"
    assert confidence_band(0.82) == "strong"
    assert confidence_band(0.7) == "adequate"
    assert confidence_band(0.62) == "adequate"
    assert confidence_band(0.5) == "thin"
    assert confidence_band(0.99, contested=True) == "flagged"
    assert confidence_band(None) == "thin"


def test_legal_adapter_verified_only():
    envelope = {
        "status": "done",
        "evidence": {
            "task": "qualified immunity research for counsel",
            "authorities": [
                {
                    "case_name": "Good Case",
                    "holding": "A holding",
                    "url": "https://www.courtlistener.com/opinion/123/good-case/",
                    "citation": "1 F.3d 1",
                },
                {
                    # should be stripped — not a real URL
                    "case_name": "Bad",
                    "holding": "x",
                    "url": "not-a-url",
                    "citation": "",
                },
            ],
            "dropped": [{"case_name": "Uncited claim", "drop_reason": "no verified URL"}],
            "evidence_verdict": "sufficient",
            "evidence_score": 0.85,
            "contested": False,
            "autonomy_gate": "allow",
            "decision_disposition": "proceed",
            "needs_attorney": ["Confirm jurisdiction."],
            "provider": "ollama",
        },
    }
    b = adapt_legal_research(envelope)
    assert b.kind == "legal_research"
    assert b.confidence_band == "strong"
    assert b.dropped_count == 1
    assert len(b.authorities) == 1
    assert b.authorities[0].verified
    d = b.to_dict()
    # unverified never appears
    assert all(a["verified"] and a["url"].startswith("http") for a in d["authorities"])
    assert len(d["authorities"]) == 1


def test_legal_contested_flagged():
    envelope = {
        "status": "escalate",
        "evidence": {
            "task": "split authority issue",
            "authorities": [],
            "dropped": [],
            "evidence_verdict": "contested",
            "evidence_score": 0.9,
            "contested": True,
            "evidence_reason": "circuits disagree",
            "autonomy_gate": "escalate",
            "decision_disposition": "escalated",
            "needs_attorney": ["Resolve CONTESTED authority."],
        },
    }
    b = adapt_legal_research(envelope)
    assert b.contested
    assert b.confidence_band == "flagged"
    assert "disagree" in b.contested_reason


def test_repo_steward_adapter_needs_judgment():
    envelope = {
        "status": "done",
        "evidence": {
            "task": "steward inspect .",
            "proposals": [
                {
                    "action": "report missing MEMORY.md",
                    "gate": "require_briefing",
                    "escalated": False,
                    "finding": {"path": "MEMORY.md", "checker": "knowledge_present"},
                },
                {
                    "action": "delete secrets from NOTES.md and rotate credentials",
                    "gate": "escalate",
                    "escalated": True,
                    "finding": {"path": "NOTES.md"},
                },
            ],
            "decision_disposition": "escalated",
            "provider": "local",
        },
    }
    b = adapt_repo_steward(envelope)
    assert b.kind == "repo_steward"
    assert b.disposition == "escalated"
    assert b.authorities == []  # no external citations
    assert any("ESCALATED" in n or "delete secrets" in n for n in b.needs_judgment)


def test_observe_adapter_actionable_only_as_authority():
    envelope = {
        "feed": "usgs",
        "result": {
            "events": [
                {
                    "title": "Fresh multi-source event",
                    "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us1",
                    "actionable": True,
                    "source_id": "usgs_earthquakes",
                },
                {
                    "title": "Stale lone",
                    "url": "https://example.com/old",
                    "actionable": False,
                    "freshness_grade": "stale",
                    "source_id": "gdelt",
                },
                {
                    "title": "No url",
                    "url": "",
                    "actionable": True,
                },
            ],
            "assessment_verdict": "weak",
            "assessment_score": 0.4,
            "actionable_count": 1,
            "non_actionable_count": 2,
            "decision_disposition": "escalated",
        },
    }
    b = adapt_observe(envelope)
    assert b.kind == "observe"
    assert len(b.authorities) == 1
    assert b.authorities[0].verified
    assert b.dropped_count == 2
    assert any("Stale" in n or "stale" in n for n in b.needs_judgment)


def test_profile_override_does_not_change_data():
    envelope = {
        "status": "done",
        "evidence": {
            "task": "issue X",
            "authorities": [{
                "case_name": "A",
                "url": "https://www.courtlistener.com/opinion/1/a/",
                "holding": "h",
            }],
            "dropped": [],
            "evidence_score": 0.7,
            "decision_disposition": "proceed",
            "needs_attorney": ["Check circuit."],
            "contested": False,
        },
    }
    b = adapt_envelope(envelope, kind="legal_research")
    base = b.to_dict()
    g = apply_profile(base, "generic")
    leg = apply_profile(base, "legal")
    assert g["profile"]["judgment_label"] == GENERIC_PROFILE["judgment_label"]
    assert "attorney" not in g["profile"]["judgment_label"].lower()
    assert "Not legal advice" not in g["profile"]["disclaimer"]
    assert leg["profile"]["judgment_label"] == LEGAL_PROFILE["judgment_label"]
    assert "attorney" in leg["profile"]["judgment_label"].lower()
    assert "Not legal advice" in leg["profile"]["disclaimer"]
    # domain data identical
    assert g["question"] == leg["question"]
    assert g["authorities"] == leg["authorities"]
    assert g["disposition"] == leg["disposition"]


def test_record_brief_and_load(tmp_path):
    envelope = {
        "status": "done",
        "evidence": {
            "task": "research for counsel: immunity",
            "authorities": [{
                "case_name": "Case A",
                "url": "https://www.courtlistener.com/opinion/99/case-a/",
                "citation": "1 F.3d 1",
                "holding": "holding text",
            }],
            "dropped": [{"case_name": "Dropped claim"}],
            "evidence_verdict": "sufficient",
            "evidence_score": 0.88,
            "contested": False,
            "autonomy_gate": "allow",
            "decision_disposition": "proceed",
            "needs_attorney": ["Verify full opinion."],
            "provider": "ollama",
        },
    }
    entry = record_brief(envelope, kind="legal_research", log_dir=tmp_path)
    assert (tmp_path / "briefs.jsonl").is_file()
    assert entry.get("kind") == "legal_research"
    assert entry.get("dropped_count") == 1
    assert len(entry.get("authorities") or []) == 1

    loaded = load_brief("latest", log_dir=tmp_path, profile="generic")
    assert loaded.get("empty") is not True
    assert loaded["question"]
    assert loaded["profile"]["id"] == "generic"
    assert loaded["authorities"][0]["verified"] is True

    legal = load_brief("latest", log_dir=tmp_path, profile="legal")
    assert legal["profile"]["judgment_label"] == LEGAL_PROFILE["judgment_label"]

    runs = list_briefs(tmp_path)
    assert runs


def test_missing_briefs_empty_not_500(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    out = load_brief("latest", log_dir=empty, profile="generic")
    assert out.get("empty") is True
    assert out.get("authorities") == []
    assert "profile" in out


def test_html_self_contained_no_cdn():
    assert "cdn." not in BRIEF_HTML.lower()
    assert "https://" not in BRIEF_HTML
    assert "http://" not in BRIEF_HTML
    assert "READ-ONLY" in BRIEF_HTML
    assert "/brief/data" in BRIEF_HTML
    assert "method=\"POST\"" not in BRIEF_HTML.lower()
    # generic default labels, not legal-specific
    assert "Not legal advice" not in BRIEF_HTML
    assert "attorney" not in BRIEF_HTML.lower() or "legal (sample)" in BRIEF_HTML.lower()


@pytest.mark.asyncio
async def test_brief_routes():
    from src.api import server
    from fastapi.responses import HTMLResponse

    html = await server.brief_page()
    assert isinstance(html, HTMLResponse)
    body = html.body.decode("utf-8") if isinstance(html.body, (bytes, bytearray)) else str(html.body)
    assert "Governed brief" in body or "READ-ONLY" in body

    data = await server.brief_data(run="latest", profile="generic", list=False)
    assert data.get("read_only") is True
    assert "authorities" in data or data.get("empty")

    listing = await server.brief_data(run="latest", profile="generic", list=True)
    assert "runs" in listing


def test_brief_routes_get_only():
    from src.api import server
    for r in server.app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None) or set()
        if path and path.startswith("/brief"):
            assert "POST" not in methods
            assert "PUT" not in methods
            assert "DELETE" not in methods
            assert "GET" in methods
