"""GDELT 2.0 Doc API — keyless world-event articles.

Live: https://api.gdeltproject.org/api/v2/doc/doc?...&format=json
Note: host can be slow/unavailable; adapter fails safe to [].
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from src.observe.schema import ObserveEvent

DEFAULT_QUERY = "earthquake OR wildfire OR conflict OR market"
DEFAULT_URL = (
    "https://api.gdeltproject.org/api/v2/doc/doc"
    f"?query={quote(DEFAULT_QUERY)}&mode=ArtList&maxrecords=15&format=json&sort=datedesc"
)


def _parse_seendate(s: str) -> str:
    """GDELT seendate like 20260710T120000Z → ISO-8601."""
    if not s:
        return datetime.now(tz=timezone.utc).isoformat()
    try:
        # 20260710T120000Z
        if len(s) >= 15 and s[8] == "T":
            dt = datetime.strptime(s[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
            return dt.isoformat()
    except Exception:
        pass
    return datetime.now(tz=timezone.utc).isoformat()


def parse_payload(data: dict[str, Any], *, now: str | None = None) -> list[ObserveEvent]:
    """Parse GDELT ArtList JSON. Pure; no network."""
    if not isinstance(data, dict):
        return []
    now = now or datetime.now(tz=timezone.utc).isoformat()
    articles = data.get("articles") or data.get("Articles") or []
    out: list[ObserveEvent] = []
    for i, art in enumerate(articles):
        try:
            title = (art.get("title") or "").strip()
            url = (art.get("url") or "").strip()
            if not title and not url:
                continue
            domain = art.get("domain") or ""
            country = art.get("sourcecountry") or ""
            seendate = art.get("seendate") or art.get("seenDate") or ""
            eid = url or f"gdelt:{i}:{title[:40]}"
            out.append(ObserveEvent(
                event_id=f"gdelt:{hash(eid) & 0xFFFFFFFF:08x}",
                source_id="gdelt",
                source_type="news",
                title=title or domain,
                summary=f"{domain} · {country}".strip(" ·"),
                category="world_event",
                ts=_parse_seendate(seendate),
                first_seen_at=now,
                lat=None,
                lng=None,
                salience=0.55,
                url=url,
                provenance=[url, DEFAULT_URL] if url else [DEFAULT_URL],
            ))
        except Exception:
            continue
    return out


def fetch(url: str = DEFAULT_URL) -> list[ObserveEvent]:
    """Fetch live GDELT ArtList. Fail-safe: [] on any error."""
    from src.observe.adapters._http import fetch_json
    data = fetch_json(url, timeout=25.0)
    if not data:
        return []
    return parse_payload(data)
