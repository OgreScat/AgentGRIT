"""USGS earthquake GeoJSON feed — keyless, public.

Live: https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_month.geojson
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.observe.schema import ObserveEvent

DEFAULT_URL = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_month.geojson"
)


def _iso_from_ms(ms: Any) -> str:
    try:
        return datetime.fromtimestamp(float(ms) / 1000.0, tz=timezone.utc).isoformat()
    except Exception:
        return datetime.now(tz=timezone.utc).isoformat()


def parse_payload(data: dict[str, Any], *, now: str | None = None) -> list[ObserveEvent]:
    """Parse USGS GeoJSON into ObserveEvents. Pure; no network."""
    if not isinstance(data, dict):
        return []
    now = now or datetime.now(tz=timezone.utc).isoformat()
    out: list[ObserveEvent] = []
    for feat in data.get("features") or []:
        try:
            props = feat.get("properties") or {}
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates") or [None, None, None]
            lng, lat = coords[0], coords[1]
            eid = str(feat.get("id") or props.get("code") or props.get("ids") or "")
            if not eid:
                continue
            mag = props.get("mag")
            place = props.get("place") or ""
            title = props.get("title") or f"M{mag} earthquake — {place}"
            sal = 0.5
            try:
                m = float(mag)
                sal = max(0.2, min(1.0, m / 8.0))
            except (TypeError, ValueError):
                pass
            url = props.get("url") or f"https://earthquake.usgs.gov/earthquakes/eventpage/{eid}"
            out.append(ObserveEvent(
                event_id=f"usgs:{eid}",
                source_id="usgs_earthquakes",
                source_type="seismic",
                title=title,
                summary=f"Magnitude {mag} near {place}".strip(),
                category="natural_disaster",
                ts=_iso_from_ms(props.get("time")),
                first_seen_at=now,
                lat=float(lat) if lat is not None else None,
                lng=float(lng) if lng is not None else None,
                salience=sal,
                url=url,
                provenance=[url, DEFAULT_URL],
            ))
        except Exception:
            continue
    return out


def fetch(url: str = DEFAULT_URL) -> list[ObserveEvent]:
    """Fetch live USGS feed. Fail-safe: returns [] on network/parse error."""
    from src.observe.adapters._http import fetch_json
    data = fetch_json(url)
    if not data:
        return []
    return parse_payload(data)
