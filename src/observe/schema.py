"""Canonical observation schema — deterministic, provenance-bearing."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ObserveEvent:
    """One normalized observation from a live (or fixture) feed.

    Every event must trace to a real source via provenance + url.
    Grades (freshness/evidence) are filled by fuse; actionable by gate.
    """

    event_id: str
    source_id: str
    source_type: str
    title: str
    summary: str
    category: str
    ts: str  # observed_at / event time (ISO-8601)
    first_seen_at: str  # when GRIT first saw it (ISO-8601)
    lat: float | None = None
    lng: float | None = None
    salience: float = 0.5  # 0..1
    url: str = ""
    provenance: list[str] = field(default_factory=list)
    freshness_grade: str = "unknown"  # fresh | aging | stale | unknown
    evidence_grade: float = 0.0  # 0..1 after fuse
    actionable: bool = False  # set only by gate; default refuse
    corroborating_sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_research_result(self) -> dict[str, Any]:
        """Shape expected by research_quality.quality_of / assess."""
        return {
            "provider": self.source_id,
            "content": f"{self.title}. {self.summary}".strip(),
            "urls": [self.url] if self.url else list(self.provenance),
            "ts": self.ts,
        }
