"""Shared fail-safe HTTP JSON fetch — never raises to callers."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

_UA = "AgentGRIT-observe/0 (+https://github.com/OgreScat/AgentGRIT)"


def fetch_json(url: str, timeout: float = 20.0) -> Any | None:
    """GET JSON from url. Returns None on any failure (timeout, HTTP, parse)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        return json.loads(raw.decode("utf-8", errors="replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
        return None
    except Exception:
        return None
