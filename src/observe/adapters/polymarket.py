"""Polymarket public markets API — keyless prediction-market odds.

Live: https://gamma-api.polymarket.com/events?limit=N&active=true
No API key required for public event listings.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.observe.schema import ObserveEvent

DEFAULT_URL = "https://gamma-api.polymarket.com/events?limit=15&active=true&closed=false"


def _yes_price(market: dict[str, Any]) -> float | None:
    """Extract Yes probability from outcomePrices if present."""
    prices = market.get("outcomePrices")
    outcomes = market.get("outcomes")
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except Exception:
            return None
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except Exception:
            outcomes = None
    if not prices:
        return None
    try:
        if outcomes and isinstance(outcomes, list):
            for o, p in zip(outcomes, prices):
                if str(o).lower() in ("yes", "y"):
                    return float(p)
        return float(prices[0])
    except (TypeError, ValueError, IndexError):
        return None


def parse_payload(data: Any, *, now: str | None = None) -> list[ObserveEvent]:
    """Parse Polymarket gamma events list. Pure; no network."""
    if isinstance(data, dict):
        events = data.get("events") or data.get("data") or []
    elif isinstance(data, list):
        events = data
    else:
        return []
    now = now or datetime.now(tz=timezone.utc).isoformat()
    out: list[ObserveEvent] = []
    for ev in events:
        try:
            eid = str(ev.get("id") or ev.get("slug") or "")
            if not eid:
                continue
            title = (ev.get("title") or ev.get("slug") or "market").strip()
            desc = (ev.get("description") or "")[:300]
            markets = ev.get("markets") or []
            if markets and isinstance(markets[0], str):
                markets = [json.loads(m) for m in markets[:3]]
            top = markets[0] if markets else {}
            if isinstance(top, str):
                top = json.loads(top)
            q = (top.get("question") or title) if isinstance(top, dict) else title
            yes = _yes_price(top) if isinstance(top, dict) else None
            summary = q
            if yes is not None:
                summary = f"{q} — Yes≈{yes:.0%}"
            vol = ev.get("volume") or (top.get("volume") if isinstance(top, dict) else None)
            try:
                sal = max(0.2, min(1.0, float(vol or 0) / 1_000_000.0))
            except (TypeError, ValueError):
                sal = 0.4
            ts = ev.get("startDate") or ev.get("creationDate") or now
            slug = ev.get("slug") or eid
            url = f"https://polymarket.com/event/{slug}"
            out.append(ObserveEvent(
                event_id=f"polymarket:{eid}",
                source_id="polymarket",
                source_type="prediction_market",
                title=title,
                summary=summary,
                category="market",
                ts=str(ts),
                first_seen_at=now,
                lat=None,
                lng=None,
                salience=sal,
                url=url,
                provenance=[url, DEFAULT_URL],
            ))
        except Exception:
            continue
    return out


def fetch(url: str = DEFAULT_URL) -> list[ObserveEvent]:
    """Fetch live Polymarket events. Fail-safe: [] on any error."""
    from src.observe.adapters._http import fetch_json
    data = fetch_json(url)
    if data is None:
        return []
    return parse_payload(data)
