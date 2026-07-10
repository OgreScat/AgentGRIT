"""Autonomy is BINDING on router.execute — not advisory."""

import pytest

from src.governance.autonomy import (
    AutonomyGate,
    classify_action_risk,
    decide,
    must_stop,
    may_auto_act,
)
from src.governance.trust import TrustLevel
from src.execution.router import LLMRouter


def test_classify_low_for_format():
    assert classify_action_risk("format this file and add docstrings") == 10


def test_classify_high_for_deploy_secrets():
    r = classify_action_risk("deploy to production and rotate secrets")
    assert r >= 30


def test_classify_critical_for_wire_transfer():
    assert classify_action_risk("execute a wire transfer of funds to the vendor") == 40


def test_classify_empty_fails_high():
    assert classify_action_risk("") == 30
    assert classify_action_risk(None) == 30  # type: ignore[arg-type]


def test_must_stop_only_deny_escalate():
    allow = decide(risk="low", trust="autonomous")
    brief = decide(risk="low", trust="untrusted")
    esc = decide(risk="high", trust="autonomous")
    deny = decide(risk="low", trust="autonomous", bylaw_action="block")
    assert not must_stop(allow) and may_auto_act(allow)
    assert not must_stop(brief) and not may_auto_act(brief)
    assert must_stop(esc)
    assert must_stop(deny)
    assert brief.gate is AutonomyGate.REQUIRE_BRIEFING


@pytest.mark.asyncio
async def test_router_high_risk_stops_via_autonomy(monkeypatch, tmp_path):
    """HIGH risk + bylaw PROCEED must not call a model."""
    called = {"ollama": 0}

    async def fake_ollama(self, prompt):
        called["ollama"] += 1
        return "should-not-run", 1

    # Isolate trust so UNTRUSTED/LOW would REQUIRE_BRIEFING; HIGH still stops.
    from src.governance import trust as trust_mod
    monkeypatch.setattr(
        trust_mod,
        "get_trust_manager",
        lambda: type("T", (), {
            "get_trust_level": lambda self, p: TrustLevel.AUTONOMOUS,
        })(),
    )

    router = LLMRouter({"ollama_model": "gemma4:12b"})
    monkeypatch.setattr(LLMRouter, "_call_ollama", fake_ollama)

    result = await router.execute(
        "execute a wire transfer of funds to the vendor account",
        force_provider="ollama",
    )
    assert result["provider"] == "autonomy"
    assert result["autonomy_gate"] == "escalate"
    assert result.get("risk_level", 0) >= 30
    assert called["ollama"] == 0
    assert result["tokens"] == 0


@pytest.mark.asyncio
async def test_router_low_risk_still_runs(monkeypatch):
    """LOW risk with trusted/autonomous trust may reach the model."""
    called = {"ollama": 0}

    async def fake_ollama(self, prompt):
        called["ollama"] += 1
        return "formatted ok", 12

    from src.governance import trust as trust_mod
    monkeypatch.setattr(
        trust_mod,
        "get_trust_manager",
        lambda: type("T", (), {
            "get_trust_level": lambda self, p: TrustLevel.AUTONOMOUS,
        })(),
    )

    router = LLMRouter({"ollama_model": "gemma4:12b"})
    monkeypatch.setattr(LLMRouter, "_call_ollama", fake_ollama)

    result = await router.execute(
        "format this file and explain the helper function",
        force_provider="ollama",
    )
    assert result["provider"] == "ollama"
    assert result.get("risk_level") == 10
    assert result.get("autonomy_gate") in ("allow", "require_briefing")
    assert called["ollama"] == 1
    assert "formatted" in result["response"]
