"""Tests for the frontier quota-fallback guard.

Pins the behavior: a quota / 429 is detected, routing descends to the next cheaper
provider, the hit is logged as FRONTIER_QUOTA_HIT, and non-quota errors are left for
the caller to surface (no descent, no log).
"""

import json

from src.execution.quota_fallback import (
    PROVIDER_LADDER, descend, is_quota_error, next_provider_on_quota,
)


def test_detects_429_int():
    assert is_quota_error(429) is True
    assert is_quota_error(200) is False


def test_detects_quota_text():
    assert is_quota_error("Error: rate limit exceeded") is True
    assert is_quota_error("insufficient_quota") is True
    assert is_quota_error("connection reset by peer") is False


def test_detects_response_status():
    class _R:
        status_code = 429

    class _E(Exception):
        response = _R()

    assert is_quota_error(_E("boom")) is True


def test_descend_goes_cheaper():
    assert descend("claude-opus") == "claude-sonnet"
    assert descend("perplexity") == "ollama"


def test_descend_floor_is_none():
    assert descend("ollama") is None


def test_unknown_provider_falls_to_cheapest():
    assert descend("mystery-model") == PROVIDER_LADDER[0]


def test_next_provider_logs_and_descends(tmp_path):
    log = tmp_path / "escalations.jsonl"
    nxt = next_provider_on_quota("claude-opus", 429, project="demo", log_path=log)
    assert nxt == "claude-sonnet"
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 1
    ev = json.loads(lines[0])
    assert ev["event"] == "FRONTIER_QUOTA_HIT"
    assert ev["provider"] == "claude-opus"
    assert ev["descended_to"] == "claude-sonnet"


def test_non_quota_error_returns_none_no_log(tmp_path):
    log = tmp_path / "escalations.jsonl"
    assert next_provider_on_quota("claude-opus", "syntax error", log_path=log) is None
    assert not log.exists()


def test_fallback_disabled_logs_but_no_descent(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVIDER_FALLBACK_ON_QUOTA", "false")
    log = tmp_path / "escalations.jsonl"
    assert next_provider_on_quota("claude-opus", 429, log_path=log) is None
    assert log.exists()  # the hit is still recorded even when we do not descend
