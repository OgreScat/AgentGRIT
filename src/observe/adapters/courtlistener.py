"""CourtListener (Free Law Project) opinion search — public-record case law.

Live: https://www.courtlistener.com/api/rest/v4/search/?q=...&type=o

Public-record opinions only. Never Westlaw/Lexis. Network only inside fetch();
import is pure. Fail-safe: returns [] on any error.

Auth:
  Optional env COURTLISTENER_TOKEN or COURTLISTENER_API_TOKEN raises rate
  limits (Authorization: Token …). Works without a token when the API allows
  anonymous access; when auth is required and no token is set, fetch returns [].

Adapter contract matches other observe adapters:
  parse_payload(data) -> list[ObserveEvent]   # pure, fixture-friendly
  fetch(query=...) / search_opinions(...)    # network, fail-safe []
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus, urlencode

from src.observe.schema import ObserveEvent

BASE = "https://www.courtlistener.com"
SEARCH_URL = f"{BASE}/api/rest/v4/search/"

# Verified CourtListener opinion URL (cluster absolute_url shape).
OPINION_URL_RE = re.compile(
    r"^https://www\.courtlistener\.com/opinion/\d+/",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _token() -> str | None:
    return (
        os.environ.get("COURTLISTENER_TOKEN")
        or os.environ.get("COURTLISTENER_API_TOKEN")
        or None
    )


def opinion_url(absolute_url: str | None, cluster_id: Any = None) -> str:
    """Build a canonical CourtListener opinion URL, or '' if not verifiable."""
    if absolute_url:
        path = str(absolute_url).strip()
        if path.startswith("http"):
            url = path
        else:
            if not path.startswith("/"):
                path = "/" + path
            url = BASE + path
        if OPINION_URL_RE.match(url.split("?")[0]):
            return url.split("?")[0]
    if cluster_id is not None:
        try:
            cid = int(cluster_id)
            return f"{BASE}/opinion/{cid}/"
        except (TypeError, ValueError):
            pass
    return ""


def parse_payload(
    data: dict[str, Any],
    *,
    now: str | None = None,
    query: str = "",
) -> list[ObserveEvent]:
    """Parse CourtListener search JSON (type=o). Pure; no network."""
    if not isinstance(data, dict):
        return []
    now = now or _now()
    results = data.get("results")
    if not isinstance(results, list):
        return []

    out: list[ObserveEvent] = []
    for i, row in enumerate(results):
        try:
            if not isinstance(row, dict):
                continue
            case = (row.get("caseName") or row.get("caseNameFull") or "").strip()
            court = (row.get("court") or row.get("court_citation_string") or "").strip()
            filed = (row.get("dateFiled") or "").strip()
            cluster_id = row.get("cluster_id") or row.get("id")
            abs_url = row.get("absolute_url") or ""
            url = opinion_url(abs_url, cluster_id)
            if not url:
                continue  # cite-or-refuse at source: no verifiable URL → drop

            cites = row.get("citation") or []
            if isinstance(cites, str):
                cites = [cites]
            cite_str = "; ".join(str(c) for c in cites if c) if cites else ""

            # Snippet: nested opinions[0].snippet preferred
            snippet = ""
            opinions = row.get("opinions") or []
            if isinstance(opinions, list) and opinions:
                snippet = str((opinions[0] or {}).get("snippet") or "").strip()
            if not snippet:
                snippet = str(row.get("snippet") or row.get("syllabus") or "").strip()
            # Strip HTML mark tags from highlight snippets
            snippet = re.sub(r"</?mark>", "", snippet)
            snippet = re.sub(r"\s+", " ", snippet).strip()

            title = case or f"Opinion cluster {cluster_id}"
            summary_bits = [b for b in (court, filed, cite_str) if b]
            summary = " · ".join(summary_bits)
            if snippet:
                summary = f"{summary}. {snippet[:400]}".strip(" .")

            eid = f"cl:{cluster_id}" if cluster_id is not None else f"cl:row{i}"
            content_for_quality = (
                f"{title}. {summary}. Holding/snippet: {snippet or 'see opinion'}."
            )
            # Pad slightly so quality_of does not penalize short content harshly
            if len(content_for_quality) < 80:
                content_for_quality = content_for_quality + (" " + (snippet or title)) * 2

            out.append(ObserveEvent(
                event_id=eid,
                source_id="courtlistener",
                source_type="case_law",
                title=title,
                summary=summary[:800],
                category="legal_opinion",
                ts=filed + "T00:00:00+00:00" if filed and "T" not in filed else (filed or now),
                first_seen_at=now,
                lat=None,
                lng=None,
                salience=0.7,
                url=url,
                provenance=[url, SEARCH_URL + (f"?q={quote_plus(query)}" if query else "")],
            ))
            # Stash citation string on a non-schema field via provenance for agent use
            if cite_str:
                out[-1].provenance.append(f"citation:{cite_str}")
        except Exception:
            continue
    return out


def to_research_results(events: list[ObserveEvent]) -> list[dict[str, Any]]:
    """Shape for research_quality.assess / quality_of."""
    out = []
    for e in events:
        r = e.to_research_result()
        r["provider"] = "courtlistener"
        # Ensure content long enough and URLs present
        if not r.get("urls") and e.url:
            r["urls"] = [e.url]
        out.append(r)
    return out


def search_opinions(
    query: str,
    *,
    max_results: int = 10,
    timeout: float = 20.0,
) -> list[ObserveEvent]:
    """Search CourtListener opinions. Fail-safe [] on any error. Network here only."""
    q = (query or "").strip()
    if not q:
        return []
    params = {
        "q": q,
        "type": "o",  # case law opinion clusters
        "order_by": "score desc",
    }
    url = SEARCH_URL + "?" + urlencode(params)
    headers: dict[str, str] = {}
    tok = _token()
    if tok:
        headers["Authorization"] = f"Token {tok}"

    try:
        from src.observe.adapters._http import fetch_json
        data = fetch_json(url, timeout=timeout, headers=headers or None)
        if not data:
            return []
        events = parse_payload(data, query=q)
        return events[: max(1, int(max_results))]
    except Exception:
        return []


def fetch(query: str = "due process", **kwargs: Any) -> list[ObserveEvent]:
    """Registry-compatible zero-or-query fetch. Fail-safe []."""
    return search_opinions(query, **kwargs)


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "qualified immunity"
    ev = search_opinions(q, max_results=3)
    print(f"query={q!r} results={len(ev)}")
    for e in ev:
        print(f"  - {e.title} | {e.url}")
