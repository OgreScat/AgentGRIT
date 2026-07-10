"""Fuse: dedupe + freshness TTL + cross-source corroboration grading.

This is the 10x over a raw world-state feed: lone sources score lower;
two or more independent sources on the same topic raise evidence_grade.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable

from .schema import ObserveEvent

# Freshness TTL (hours)
_FRESH_H = 24.0
_AGING_H = 72.0

_STOP = frozenset(
    "the a an of and or for to in on at by from with near after before "
    "is are was were be been being this that these those mag m".split()
)
_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {
        w for w in _WORD.findall((text or "").lower())
        if w not in _STOP and len(w) > 2
    }


def _parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        s = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def grade_freshness(ts: str, *, now: datetime | None = None) -> str:
    """fresh | aging | stale | unknown based on age of event ts."""
    dt = _parse_ts(ts)
    if not dt:
        return "unknown"
    now = now or datetime.now(tz=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_h = (now - dt).total_seconds() / 3600.0
    if age_h < 0:
        age_h = 0.0
    if age_h <= _FRESH_H:
        return "fresh"
    if age_h <= _AGING_H:
        return "aging"
    return "stale"


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _geo_close(a: ObserveEvent, b: ObserveEvent, deg: float = 2.0) -> bool:
    if a.lat is None or a.lng is None or b.lat is None or b.lng is None:
        return False
    return abs(a.lat - b.lat) <= deg and abs(a.lng - b.lng) <= deg


def _same_cluster(a: ObserveEvent, b: ObserveEvent) -> bool:
    """Topic/geo overlap → treat as same real-world event for corroboration."""
    if a.event_id == b.event_id:
        return True
    ta, tb = _tokens(a.title + " " + a.summary), _tokens(b.title + " " + b.summary)
    if _jaccard(ta, tb) >= 0.35:
        return True
    if _geo_close(a, b) and a.category == b.category:
        return True
    # Shared strong tokens (e.g. place names) + same day
    if len(ta & tb) >= 2 and a.category == b.category:
        return True
    return False


def fuse(
    events: Iterable[ObserveEvent],
    *,
    now: datetime | None = None,
) -> list[ObserveEvent]:
    """Dedupe near-duplicates, grade freshness, score cross-source evidence.

    Returns a new list (does not mutate inputs' identity beyond field copies).
    """
    now = now or datetime.now(tz=timezone.utc)
    items = list(events)
    if not items:
        return []

    # Cluster indices
    clusters: list[list[int]] = []
    assigned = [-1] * len(items)
    for i, e in enumerate(items):
        if assigned[i] >= 0:
            continue
        cluster = [i]
        assigned[i] = len(clusters)
        for j in range(i + 1, len(items)):
            if assigned[j] >= 0:
                continue
            if _same_cluster(e, items[j]):
                assigned[j] = assigned[i]
                cluster.append(j)
        clusters.append(cluster)

    fused: list[ObserveEvent] = []
    for cluster in clusters:
        members = [items[i] for i in cluster]
        # Prefer highest salience as representative
        members.sort(key=lambda x: x.salience, reverse=True)
        primary = members[0]
        sources = sorted({m.source_id for m in members})
        urls = []
        for m in members:
            if m.url and m.url not in urls:
                urls.append(m.url)
        prov = []
        for m in members:
            for p in m.provenance:
                if p not in prov:
                    prov.append(p)

        # Freshness from primary ts
        fresh = grade_freshness(primary.ts, now=now)

        # Evidence: base by source count + salience; lone source capped
        n_src = len(sources)
        if n_src >= 3:
            base = 0.85
        elif n_src == 2:
            base = 0.72
        else:
            base = 0.48  # lone source — lower, cannot alone authorize action
        grade = min(1.0, base + 0.1 * primary.salience)
        if fresh == "stale":
            grade = min(grade, 0.35)
        elif fresh == "aging":
            grade = min(grade, 0.60)

        fused.append(ObserveEvent(
            event_id=primary.event_id,
            source_id=primary.source_id if n_src == 1 else "+".join(sources),
            source_type=primary.source_type,
            title=primary.title,
            summary=primary.summary,
            category=primary.category,
            ts=primary.ts,
            first_seen_at=min((m.first_seen_at for m in members), default=primary.first_seen_at),
            lat=primary.lat,
            lng=primary.lng,
            salience=max(m.salience for m in members),
            url=primary.url or (urls[0] if urls else ""),
            provenance=prov or urls,
            freshness_grade=fresh,
            evidence_grade=round(grade, 3),
            actionable=False,  # gate decides
            corroborating_sources=sources,
        ))

    fused.sort(key=lambda e: (e.evidence_grade, e.salience), reverse=True)
    return fused
