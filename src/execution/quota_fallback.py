"""Frontier quota resilience -- when a gatekept model says 'no', descend the ladder.

Motivation (2026-07): frontier models are increasingly rate-capped -- e.g. a new
flagship shipping at 50% of the weekly limit, with routine work routed back to an
older model. Cost-first routing must treat a quota / 429 not as a fatal error but as
a signal to route DOWN to the next capable, cheaper provider, and to record the event
so the gatekeeping pattern stays visible.

Deterministic and side-effect-light: detection is a pure function; the only I/O is an
append to logs/escalations.jsonl when a frontier quota is actually hit.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

# Cost-ordered ladder, cheapest first. Mirrors router_v2.Provider ordering.
PROVIDER_LADDER = [
    "ollama",
    "perplexity",
    "grok",
    "claude-haiku",
    "claude-sonnet",
    "claude-opus",
]

_QUOTA_MARKERS = (
    "429", "quota", "rate limit", "rate_limit", "ratelimit",
    "too many requests", "insufficient_quota", "overloaded",
    "capacity", "usage limit", "resource_exhausted",
)

_LOG = Path(__file__).resolve().parents[2] / "logs" / "escalations.jsonl"


def is_quota_error(err: object) -> bool:
    """True if `err` represents a provider quota / rate / capacity refusal.

    Accepts an int status code, an exception, or any object whose str() carries a
    quota marker. Pure -- no side effects.
    """
    if err is None or isinstance(err, bool):
        return False
    if isinstance(err, int):
        return err == 429
    # httpx.HTTPStatusError and friends expose .response.status_code
    status = getattr(getattr(err, "response", None), "status_code", None)
    if status == 429:
        return True
    text = str(err).lower()
    return any(m in text for m in _QUOTA_MARKERS)


def descend(provider: str, ladder: list[str] | None = None) -> str | None:
    """Return the next cheaper provider below `provider`, or None at the floor.

    Cheaper = earlier in the ladder. An unknown provider falls to the cheapest
    option -- we fail toward free/local, never toward something more expensive.
    """
    lad = ladder or PROVIDER_LADDER
    if provider not in lad:
        return lad[0] if lad else None
    i = lad.index(provider)
    return lad[i - 1] if i > 0 else None


def fallback_enabled() -> bool:
    return os.environ.get("PROVIDER_FALLBACK_ON_QUOTA", "true").lower() not in (
        "0", "false", "no")


def log_frontier_quota_hit(provider: str, project: str = "", detail: str = "",
                           log_path: Path | None = None) -> dict:
    """Append a FRONTIER_QUOTA_HIT escalation event. Returns it. Never raises."""
    event = {
        "ts": datetime.now().isoformat(),
        "event": "FRONTIER_QUOTA_HIT",
        "provider": provider,
        "project": project,
        "detail": str(detail)[:300],
        "descended_to": descend(provider),
    }
    try:
        p = log_path or _LOG
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:  # noqa: BLE001
        pass
    return event


def next_provider_on_quota(provider: str, err: object, *, project: str = "",
                           log_path: Path | None = None) -> str | None:
    """Policy entry point. Given a provider and the error it raised, decide the next
    provider to try.

    Returns None when it is not a quota error (the caller should surface the real
    error), when fallback is disabled, or when the ladder floor is reached. A genuine
    quota hit is always logged, even when we choose not to descend.
    """
    if not is_quota_error(err):
        return None
    log_frontier_quota_hit(
        provider, project=project,
        detail=err if isinstance(err, str) else repr(err), log_path=log_path)
    if not fallback_enabled():
        return None
    return descend(provider)
