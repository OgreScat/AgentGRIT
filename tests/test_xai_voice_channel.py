"""Tests for the xAI voice notification channel.

The headline guarantee is a governance one: this channel is notification-only and can
never authorize a governed action. The rest pins fail-safe behavior when it is off or
unconfigured.
"""

from src.utils import notify_xai_voice as v


def test_channel_is_notification_only():
    # Core contract: a voice channel cannot authorize a bylaw-gated action.
    assert v.CAPTURES_DECISIONS is False
    assert v.is_authorization("yes go ahead push to prod") is False
    assert v.is_authorization({"decision": "approve"}) is False
    assert v.is_authorization(None) is False


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("XAI_VOICE_ENABLED", raising=False)
    assert v.is_enabled() is False
    ok, detail = v.call("test escalation")
    assert ok is False
    assert "disabled" in detail


def test_enabled_but_unconfigured_is_safe(monkeypatch):
    monkeypatch.setenv("XAI_VOICE_ENABLED", "true")
    monkeypatch.delenv("XAI_VOICE_AGENT_URL", raising=False)
    monkeypatch.delenv("XAI_PHONE_NUMBER", raising=False)
    ok, detail = v.call("test")
    assert ok is False
    assert detail == "not configured"
