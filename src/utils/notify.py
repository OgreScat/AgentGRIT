"""
Pluggable notifications for AgentGRIT.

The engine needs to reach a human when it escalates. How that message is
delivered is the operator's choice -- this module is channel-agnostic and ships
with no hardcoded, platform-specific transport. Pick a channel with the
NOTIFY_CHANNEL env var:

  none      (default) do nothing -- notifications are opt-in
  log       append to logs/notifications.jsonl only
  telegram  send via a Telegram bot   (NOTIFY_TELEGRAM_BOT_TOKEN + NOTIFY_TELEGRAM_CHAT_ID)
  webhook   HTTP POST {"text": ...}   (NOTIFY_WEBHOOK_URL)  -- Slack/Discord/SMS gateways
  command   run your own script       (NOTIFY_COMMAND, message passed as argv[1])

Every channel logs, and every channel fails safe: a delivery error is swallowed
so a notification can never crash the agent loop. See docs/NOTIFICATIONS.md.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path

_LOG = Path(__file__).resolve().parents[2] / "logs" / "notifications.jsonl"


def _log(text: str, channel: str, ok: bool) -> None:
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        with _LOG.open("a") as f:
            f.write(json.dumps({"ts": datetime.now().isoformat(),
                                "text": text, "channel": channel, "ok": ok}) + "\n")
    except Exception:
        pass


def _telegram(text: str) -> bool:
    token = os.environ.get("NOTIFY_TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("NOTIFY_TELEGRAM_CHAT_ID", "")
    if not (token and chat):
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status == 200


def _webhook(text: str) -> bool:
    url = os.environ.get("NOTIFY_WEBHOOK_URL", "")
    if not url:
        return False
    data = json.dumps({"text": text}).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return 200 <= r.status < 300


def _command(text: str) -> bool:
    cmd = os.environ.get("NOTIFY_COMMAND", "")
    if not cmd:
        return False
    r = subprocess.run([cmd, text], capture_output=True, timeout=15)
    return r.returncode == 0


_CHANNELS = {"telegram": _telegram, "webhook": _webhook, "command": _command}


def notify(text: str) -> bool:
    """Deliver a notification via the configured channel. Never raises."""
    channel = os.environ.get("NOTIFY_CHANNEL", "none").lower()
    ok = False
    if channel in _CHANNELS:
        try:
            ok = bool(_CHANNELS[channel](text))
        except Exception:
            ok = False
    _log(text, channel, ok)
    return ok
