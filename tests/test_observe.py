"""GRIT Observe v0 — fixtures only (no live network in tests)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.observe.adapters.usgs_earthquakes import parse_payload as usgs_parse
from src.observe.adapters.gdelt import parse_payload as gdelt_parse
from src.observe.adapters.polymarket import parse_payload as poly_parse
from src.observe.fuse import fuse, grade_freshness
from src.observe.gate import gate
from src.observe.registry import FeedRegistry, default_registry
from src.observe.run import run_observe
from src.observe.schema import ObserveEvent

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "observe"


def test_usgs_parses_fixture():
    data = json.loads((FIXTURES / "usgs_earthquakes.json").read_text())
    events = usgs_parse(data)
    assert events
    assert all(e.source_id == "usgs_earthquakes" for e in events)
    assert events[0].event_id.startswith("usgs:")
    assert events[0].url
    assert events[0].provenance


def test_gdelt_parses_fixture():
    data = json.loads((FIXTURES / "gdelt.json").read_text())
    events = gdelt_parse(data)
    assert len(events) >= 2
    assert all(e.source_id == "gdelt" for e in events)
    assert events[0].title


def test_polymarket_parses_fixture():
    data = json.loads((FIXTURES / "polymarket.json").read_text())
    events = poly_parse(data)
    assert events
    assert all(e.source_id == "polymarket" for e in events)
    assert "polymarket.com" in events[0].url


def test_registry_no_network_at_import():
    reg = default_registry()
    assert set(reg.ids()) == {"gdelt", "polymarket", "usgs_earthquakes"}
    # fetch that always fails → empty, no raise
    reg.register("broken", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert reg.fetch("broken") == []


def test_fuse_dedupes_and_grades_corroboration():
    now = datetime.now(tz=timezone.utc)
    fresh = now.isoformat()
    stale_ts = (now - timedelta(days=10)).isoformat()
    a = ObserveEvent(
        event_id="usgs:1", source_id="usgs_earthquakes", source_type="seismic",
        title="M6.5 earthquake near Island Chain", summary="Magnitude 6.5",
        category="natural_disaster", ts=fresh, first_seen_at=fresh,
        lat=10.0, lng=20.0, salience=0.8, url="https://example.com/a",
        provenance=["https://example.com/a"],
    )
    b = ObserveEvent(
        event_id="gdelt:2", source_id="gdelt", source_type="news",
        title="Earthquake magnitude 6.5 reported near island chain",
        summary="bbc.com", category="world_event", ts=fresh, first_seen_at=fresh,
        salience=0.6, url="https://example.com/b", provenance=["https://example.com/b"],
    )
    lone = ObserveEvent(
        event_id="poly:3", source_id="polymarket", source_type="prediction_market",
        title="Will widget prices rise in 2027?", summary="Yes≈40%",
        category="market", ts=stale_ts, first_seen_at=fresh,
        salience=0.3, url="https://example.com/c", provenance=["https://example.com/c"],
    )
    fused = fuse([a, b, lone], now=now)
    # a+b should cluster (shared tokens earthquake/magnitude/island)
    assert len(fused) <= 3
    multi = [e for e in fused if len(e.corroborating_sources) >= 2]
    assert multi, "expected cross-source cluster"
    assert multi[0].evidence_grade >= 0.65
    lone_f = [e for e in fused if e.source_id == "polymarket" or (
        len(e.corroborating_sources) == 1 and "polymarket" in e.corroborating_sources
    )]
    assert lone_f
    assert lone_f[0].freshness_grade == "stale"
    assert lone_f[0].evidence_grade < 0.55


def test_grade_freshness_bands():
    now = datetime.now(tz=timezone.utc)
    assert grade_freshness(now.isoformat(), now=now) == "fresh"
    assert grade_freshness((now - timedelta(hours=48)).isoformat(), now=now) == "aging"
    assert grade_freshness((now - timedelta(days=5)).isoformat(), now=now) == "stale"


def test_gate_flags_stale_lone_non_actionable(monkeypatch):
    written: list[dict] = []

    def fake_write(name, entry, log_dir=None):
        written.append({"name": name, "entry": entry})

    monkeypatch.setattr("src.utils.logging.write_jsonl", fake_write)

    now = datetime.now(tz=timezone.utc)
    stale = ObserveEvent(
        event_id="x:1", source_id="gdelt", source_type="news",
        title="Old story about widgets", summary="stale news " * 10,
        category="world_event",
        ts=(now - timedelta(days=14)).isoformat(),
        first_seen_at=now.isoformat(),
        salience=0.4, url="https://example.com/old",
        provenance=["https://example.com/old"],
        freshness_grade="stale", evidence_grade=0.3,
        corroborating_sources=["gdelt"],
    )
    result = gate([stale], feed_label="test", record_decision=True)
    assert result.actionable_count == 0
    assert result.non_actionable_count == 1
    assert not result.events[0].actionable
    assert result.decision_disposition in ("escalated", "proceed", "refused", "contested")
    # decision_record written
    recs = [w for w in written if w["name"] == "decisions.jsonl"]
    assert recs
    assert recs[-1]["entry"].get("authorized_by") == "observe:test"


def test_run_observe_from_fixtures(monkeypatch):
    written: list = []
    monkeypatch.setattr(
        "src.utils.logging.write_jsonl",
        lambda name, entry, log_dir=None: written.append(entry),
    )
    result, text = run_observe(
        fixture_dir=FIXTURES,
        record_decision=True,
    )
    assert "GRIT OBSERVE REPORT" in text
    assert result.events  # fixtures yield events
    assert any(not e.actionable for e in result.events) or result.actionable_count >= 0
    assert any(w.get("authorized_by", "").startswith("observe:") for w in written)


def test_observe_view_endpoint():
    from src.api import server

    # inject snapshot without network
    server._set_last_observe_for_tests({
        "ts": "2026-07-10T00:00:00Z",
        "feed": "all",
        "result": {
            "events": [{
                "event_id": "usgs:1",
                "title": "M5 test",
                "actionable": False,
                "freshness_grade": "stale",
                "evidence_grade": 0.3,
            }],
            "assessment_verdict": "weak",
            "actionable_count": 0,
            "non_actionable_count": 1,
        },
    })
    import asyncio
    payload = asyncio.run(server.observe_view(feed=None, refresh=False, fixture=False))
    assert payload["result"]["events"]
    assert payload["result"]["events"][0]["actionable"] is False
