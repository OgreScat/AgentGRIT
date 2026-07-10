"""xAI Grok Voice -- an OUTBOUND-ONLY escalation channel.

xAI's Voice Agent Builder (2026) provisions a phone number and can place real calls.
That makes it a useful *alerting* lane for GRIT: a ringing phone gets a human's
attention when a text might be missed. It is wired here as one more pluggable
notification channel, alongside the other pluggable notify channels.

HARD GOVERNANCE BOUNDARY -- read this before extending the module:
  This channel may only PLACE a call carrying a short message. It cannot, and must
  not, be used to RECEIVE authorization. A spoken 'yes, go ahead' over the phone is
  not an auditable, typed decision and MUST NOT satisfy any bylaw gate. Decisions
  stay on the text / HUD path where they are logged. `CAPTURES_DECISIONS = False` is
  a contract the tests enforce.

Opt-in and config-gated (all default off / empty):
  XAI_VOICE_ENABLED=false        # master switch
  XAI_VOICE_AGENT_URL=           # your Voice Agent Builder call endpoint
  XAI_PHONE_NUMBER=              # the number the agent should dial (yours)
  XAI_API_KEY=                   # if the endpoint requires a bearer token
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path

# Contract: notification-only. Enforced by tests/test_xai_voice_channel.py.
CAPTURES_DECISIONS = False

_LOG = Path(__file__).resolve().parents[2] / "logs" / "notifications.jsonl"


def is_enabled() -> bool:
    return os.environ.get("XAI_VOICE_ENABLED", "false").lower() in ("1", "true", "yes")


def is_authorization(_response: object = None) -> bool:
    """Always False. A voice channel can never authorize a governed action.

    Exists so callers can assert the boundary explicitly and so it is testable: no
    matter what a caller passes (a transcript, a dict, anything), it is not authority.
    """
    return False


def _log(text: str, ok: bool, detail: str) -> None:
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        with _LOG.open("a") as f:
            f.write(json.dumps({
                "ts": datetime.now().isoformat(), "channel": "xai_voice",
                "text": text, "ok": ok, "detail": detail[:200],
            }) + "\n")
    except Exception:  # noqa: BLE001
        pass


def call(text: str, to: str | None = None, timeout: float = 12.0) -> tuple[bool, str]:
    """Place an outbound alert call carrying `text`. Returns (ok, detail). Never raises.

    No-ops (returns False) unless XAI_VOICE_ENABLED and an endpoint + number are
    configured. Returns immediately after dispatch; it does not wait for, parse, or
    return any spoken response -- by design (see CAPTURES_DECISIONS).
    """
    if not is_enabled():
        return False, "xai_voice disabled"
    url = os.environ.get("XAI_VOICE_AGENT_URL", "").strip()
    number = (to or os.environ.get("XAI_PHONE_NUMBER", "")).strip()
    if not url or not number:
        _log(text, False, "missing XAI_VOICE_AGENT_URL or XAI_PHONE_NUMBER")
        return False, "not configured"
    payload = json.dumps({"to": number, "message": f"[AgentGRIT] {text}"}).encode()
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("XAI_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = getattr(r, "status", 0)
            ok = 200 <= status < 300
        _log(text, ok, f"status {status}")
        return ok, f"status {status}"
    except Exception as e:  # noqa: BLE001
        _log(text, False, f"{type(e).__name__}: {e}")
        return False, type(e).__name__
