"""Shared fail-safe HTTP JSON fetch — never raises to callers."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

_UA = "AgentGRIT-observe/0 (+https://github.com/OgreScat/AgentGRIT)"


def fetch_json(
    url: str,
    timeout: float = 20.0,
    headers: dict[str, str] | None = None,
) -> Any | None:
    """GET JSON from url. Returns None on any failure (timeout, HTTP, parse).

    Optional extra headers (e.g. Authorization) are merged over defaults.
    Never raises.
    """
    try:
        h = {"User-Agent": _UA, "Accept": "application/json"}
        if headers:
            h.update(headers)
        req = urllib.request.Request(url, headers=h)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        return json.loads(raw.decode("utf-8", errors="replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
        return None
    except Exception:
        return None
