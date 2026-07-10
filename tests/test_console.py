"""Operator console — read-only HTML + JSONL rollup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api.console_data import build_console_rollup
from src.api.console_page import CONSOLE_HTML
from src.utils.logging import read_jsonl_tail


def _plant(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    decisions = [
        {
            "ts": "2026-07-10T12:00:00",
            "disposition": "proceed",
            "action": "format helpers",
            "rationale": "low risk",
            "authorized_by": "router:allow:risk=10",
            "chosen_provider": "ollama",
        },
        {
            "ts": "2026-07-10T12:01:00",
            "disposition": "escalated",
            "action": "deploy to production",
            "rationale": "HIGH risk",
            "authorized_by": "agent:repo_steward",
        },
        {
            "ts": "2026-07-10T12:02:00",
            "disposition": "refused",
            "action": "rm -rf /",
            "rationale": "Law 0",
            "authorized_by": "bylaws",
        },
    ]
    (log_dir / "decisions.jsonl").write_text(
        "\n".join(json.dumps(d) for d in decisions) + "\n", encoding="utf-8"
    )
    (log_dir / "escalations.jsonl").write_text(
        json.dumps({
            "timestamp": "2026-07-10T12:03:00",
            "event": "escalation_created",
            "data": {
                "id": "esc1",
                "requester": "test",
                "category": "file_write",
                "risk_level": 30,
                "requires_owner": True,
                "expires_at": "2026-07-10T12:10:00",
                "status": "pending",
            },
        }) + "\n",
        encoding="utf-8",
    )
    (log_dir / "router.jsonl").write_text(
        "\n".join(json.dumps({
            "timestamp": "2026-07-10T12:00:00",
            "provider": p,
            "category": "simple_code",
            "confidence": 0.9,
        }) for p in ("ollama", "ollama", "perplexity")) + "\n",
        encoding="utf-8",
    )


def test_read_jsonl_tail(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text("\n".join(json.dumps({"i": i}) for i in range(10)) + "\n")
    # write via helper path
    from src.utils.logging import write_jsonl, read_jsonl_tail
    write_jsonl("t.jsonl", {"a": 1}, log_dir=tmp_path)
    write_jsonl("t.jsonl", {"a": 2}, log_dir=tmp_path)
    write_jsonl("t.jsonl", {"a": 3}, log_dir=tmp_path)
    tail = read_jsonl_tail("t.jsonl", n=2, log_dir=tmp_path)
    assert [x["a"] for x in tail] == [2, 3]


def test_rollup_from_planted_logs(tmp_path):
    _plant(tmp_path)
    roll = build_console_rollup(tmp_path, observe_snapshot=None, limit=40)
    assert roll["read_only"] is True
    assert len(roll["decisions"]) == 3
    # newest first
    assert roll["decisions"][0]["disposition"] == "refused"
    disps = {d["disposition"] for d in roll["decisions"]}
    assert "proceed" in disps and "escalated" in disps
    assert roll["escalations"]
    assert roll["escalations"][0]["id"] == "esc1"
    assert roll["router"]["by_provider"]["ollama"] == 2
    assert roll["router"]["by_provider"]["perplexity"] == 1
    assert roll["observe"]["available"] is False


def test_rollup_missing_logs_empty(tmp_path):
    empty = tmp_path / "empty_logs"
    empty.mkdir()
    roll = build_console_rollup(empty, limit=10)
    assert roll["decisions"] == []
    assert roll["escalations"] == []
    assert roll["router"]["total"] == 0
    assert "decisions.jsonl" in roll["missing_logs"]


def test_rollup_with_observe_snapshot(tmp_path):
    _plant(tmp_path)
    snap = {
        "ts": "2026-07-10T12:00:00Z",
        "feed": "usgs_earthquakes",
        "result": {
            "events": [{"event_id": "1"}],
            "actionable_count": 0,
            "non_actionable_count": 1,
            "assessment_verdict": "weak",
        },
    }
    roll = build_console_rollup(tmp_path, observe_snapshot=snap)
    assert roll["observe"]["available"] is True
    assert roll["observe"]["event_count"] == 1
    assert roll["observe"]["actionable_count"] == 0


@pytest.mark.asyncio
async def test_console_routes():
    from src.api import server
    from fastapi.responses import HTMLResponse

    html = await server.console_page()
    assert isinstance(html, HTMLResponse)
    body = html.body.decode("utf-8") if isinstance(html.body, (bytes, bytearray)) else str(html.body)
    assert "AgentGRIT Console" in body
    assert "READ-ONLY" in body
    assert "/console/data" in body
    # no action verbs that would POST
    assert "method=\"POST\"" not in body.lower()
    assert "fetch('/console/data'" in body or 'fetch("/console/data"' in body

    # inject log_dir via monkeypatch of DEFAULT_LOG_DIR used inside handler
    # call build path directly is enough; also hit handler with default
    data = await server.console_data(limit=10)
    assert data.get("read_only") is True
    assert "decisions" in data
    assert "escalations" in data
    assert "router" in data


def test_html_is_self_contained():
    assert "cdn." not in CONSOLE_HTML.lower()
    assert "http://" not in CONSOLE_HTML  # no external assets
    assert "https://" not in CONSOLE_HTML
    assert "<script>" in CONSOLE_HTML
    assert "<style>" in CONSOLE_HTML


def test_console_endpoints_are_get_only():
    """Grep-provable: only GET routes for /console — no POST action surface."""
    from src.api import server
    paths = []
    for r in server.app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None) or set()
        if path and path.startswith("/console"):
            paths.append((path, set(methods)))
    assert any(p == "/console" for p, _ in paths)
    assert any(p == "/console/data" for p, _ in paths)
    for path, methods in paths:
        assert "POST" not in methods
        assert "PUT" not in methods
        assert "DELETE" not in methods
        assert "GET" in methods
