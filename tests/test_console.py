"""Operator console — multi-screen read-only rollups + HTML."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api.console_data import (
    build_console_rollup,
    build_screen_rollup,
    SCREENS,
)
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
            "category": "simple_code",
            "confidence": 0.9,
            "estimated_cost_usd": 0.0,
            "route_reason": "cheapest capable",
            "bylaw_action": "proceed",
            "evidence": {"verdict": "sufficient", "score": 0.8},
        },
        {
            "ts": "2026-07-10T12:01:00",
            "disposition": "escalated",
            "action": "deploy to production",
            "rationale": "HIGH risk",
            "authorized_by": "agent:repo_steward",
            "chosen_provider": "claude-sonnet",
            "bylaw_action": "escalate",
            "evidence": {"verdict": "insufficient", "score": 0.3, "require_human": True},
        },
        {
            "ts": "2026-07-10T12:02:00",
            "disposition": "refused",
            "action": "rm -rf /",
            "rationale": "Law 0",
            "authorized_by": "bylaws",
            "bylaw_action": "block",
            "bylaw_reason": "Blocked by Law 0",
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
            "reason": f"Cheapest provider with code_generation ({p})",
            "capabilities": ["code_generation"],
            "estimated_cost_usd": 0.001 if p != "ollama" else 0.0,
            "task_preview": "format helpers",
        }) for p in ("ollama", "ollama", "perplexity")) + "\n",
        encoding="utf-8",
    )
    (log_dir / "bylaws.jsonl").write_text(
        json.dumps({
            "timestamp": "2026-07-10T12:02:00",
            "command": "rm -rf /",
            "action": "block",
            "reason": "Law 0",
            "rule": "blocked_patterns",
            "role": "developer",
        }) + "\n",
        encoding="utf-8",
    )
    (log_dir / "briefs.jsonl").write_text(
        json.dumps({
            "ts": "2026-07-10T12:05:00",
            "id": "brief1",
            "kind": "legal_research",
            "question": "case law for counsel",
            "disposition": "proceed",
            "confidence_band": "strong",
            "confidence_score": 0.86,
            "evidence_verdict": "sufficient",
            "contested": False,
            "dropped_count": 1,
            "authorities": [{"title": "A", "url": "https://example.com/a", "verified": True}],
            "autonomy_gate": "allow",
        }) + "\n" + json.dumps({
            "ts": "2026-07-10T12:06:00",
            "id": "brief2",
            "kind": "legal_research",
            "question": "split authority",
            "disposition": "escalated",
            "confidence_band": "flagged",
            "contested": True,
            "evidence_verdict": "contested",
            "dropped_count": 0,
            "authorities": [],
        }) + "\n",
        encoding="utf-8",
    )
    (log_dir / "notifications.jsonl").write_text(
        json.dumps({
            "ts": "2026-07-10T12:07:00",
            "channel": "log",
            "text": "escalation notice",
            "ok": True,
        }) + "\n",
        encoding="utf-8",
    )


def test_read_jsonl_tail(tmp_path):
    from src.utils.logging import write_jsonl, read_jsonl_tail
    write_jsonl("t.jsonl", {"a": 1}, log_dir=tmp_path)
    write_jsonl("t.jsonl", {"a": 2}, log_dir=tmp_path)
    write_jsonl("t.jsonl", {"a": 3}, log_dir=tmp_path)
    tail = read_jsonl_tail("t.jsonl", n=2, log_dir=tmp_path)
    assert [x["a"] for x in tail] == [2, 3]


def test_flat_rollup_back_compat(tmp_path):
    _plant(tmp_path)
    roll = build_console_rollup(tmp_path, limit=40)
    assert roll["read_only"] is True
    assert len(roll["decisions"]) == 3
    assert roll["decisions"][0]["disposition"] == "refused"
    assert roll["router"]["by_provider"]["ollama"] == 2


def test_rollup_missing_logs_empty(tmp_path):
    empty = tmp_path / "empty_logs"
    empty.mkdir()
    roll = build_console_rollup(empty, limit=10)
    assert roll["decisions"] == []
    assert "decisions.jsonl" in roll["missing_logs"]
    for scr in ("overview", "tasks", "governance", "research", "models", "audit"):
        s = build_screen_rollup(scr, empty, limit=5)
        assert s["read_only"] is True
        assert s.get("screen") == scr or "error" not in s or s.get("screen") == scr


def test_each_screen_shape(tmp_path):
    _plant(tmp_path)
    ov = build_screen_rollup("overview", tmp_path, limit=20)
    assert ov["screen"] == "overview"
    assert "kpis" in ov
    assert "timeline" in ov
    assert ov["kpis"]["pending_escalations"] >= 1
    assert ov["kpis"]["last_blocked"] is not None

    tasks = build_screen_rollup("tasks", tmp_path)
    assert tasks["screen"] == "tasks"
    assert len(tasks["tasks"]) == 3
    assert "filters" in tasks

    gov = build_screen_rollup("governance", tmp_path)
    assert gov["escalations"]
    assert gov["bylaws"]
    assert gov["pillars"]["available"] is False
    assert "read-only" in (gov.get("note") or "").lower() or "NOT" in (gov.get("note") or "")

    res = build_screen_rollup("research", tmp_path)
    assert res["briefs"]
    assert any(b.get("contested") for b in res["contested_briefs"])

    models = build_screen_rollup("models", tmp_path)
    assert models["by_provider"]["ollama"] == 2
    assert models["local_count"] >= 2
    assert models["why_this_model"]
    assert "soft_budget" in (models.get("budget_thresholds") or {})

    audit = build_screen_rollup("audit", tmp_path)
    assert audit["notifications"]
    assert audit["projects"]["available"] is False


@pytest.mark.asyncio
async def test_console_routes():
    from src.api import server
    from fastapi.responses import HTMLResponse

    html = await server.console_page()
    assert isinstance(html, HTMLResponse)
    body = html.body.decode("utf-8") if isinstance(html.body, (bytes, bytearray)) else str(html.body)
    assert "AgentGRIT Ops" in body or "READ-ONLY" in body
    assert "method=\"POST\"" not in body.lower()
    assert "screen=" in body or "/console/data" in body
    for s in ("overview", "tasks", "governance", "research", "models", "audit"):
        assert s in body

    flat = await server.console_data(limit=10, screen="flat")
    assert flat.get("read_only") is True
    assert "decisions" in flat

    ov = await server.console_data(limit=10, screen="overview")
    assert ov.get("read_only") is True
    assert ov.get("screen") == "overview" or "kpis" in ov


def test_html_self_contained():
    assert "cdn." not in CONSOLE_HTML.lower()
    assert "https://" not in CONSOLE_HTML
    assert "http://" not in CONSOLE_HTML
    assert "<script>" in CONSOLE_HTML
    assert "READ-ONLY" in CONSOLE_HTML


def test_console_endpoints_are_get_only():
    from src.api import server
    for r in server.app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None) or set()
        if path and path.startswith("/console"):
            assert "POST" not in methods
            assert "PUT" not in methods
            assert "DELETE" not in methods
            assert "GET" in methods


def test_screens_constant():
    assert "overview" in SCREENS
    assert "flat" in SCREENS
