"""Feed registry — pure registration; no network at import."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .schema import ObserveEvent

# Adapter contract: zero-arg callable returning list[ObserveEvent]; never raises.
FetchFn = Callable[[], list[ObserveEvent]]


@dataclass
class FeedSpec:
    id: str
    cadence_seconds: int
    fetch: FetchFn
    health: bool = True  # flipped False after consecutive empty failures by runner
    description: str = ""


@dataclass
class FeedRegistry:
    """Register observation adapters. Pure: does not call network on register."""

    _feeds: dict[str, FeedSpec] = field(default_factory=dict)

    def register(
        self,
        feed_id: str,
        fetch: FetchFn,
        *,
        cadence_seconds: int = 900,
        description: str = "",
        health: bool = True,
    ) -> None:
        if not feed_id or not callable(fetch):
            raise ValueError("feed_id and fetch callable required")
        self._feeds[feed_id] = FeedSpec(
            id=feed_id,
            cadence_seconds=int(cadence_seconds),
            fetch=fetch,
            health=health,
            description=description,
        )

    def get(self, feed_id: str) -> FeedSpec | None:
        return self._feeds.get(feed_id)

    def list_feeds(self) -> list[FeedSpec]:
        return list(self._feeds.values())

    def ids(self) -> list[str]:
        return sorted(self._feeds.keys())

    def mark_health(self, feed_id: str, healthy: bool) -> None:
        spec = self._feeds.get(feed_id)
        if spec:
            spec.health = bool(healthy)

    def fetch(self, feed_id: str) -> list[ObserveEvent]:
        """Call one adapter; never raises — empty list on any failure."""
        spec = self._feeds.get(feed_id)
        if not spec:
            return []
        try:
            out = spec.fetch()
            events = list(out or [])
            # Successful call = healthy even if feed is quiet (empty list).
            self.mark_health(feed_id, True)
            return events
        except Exception:
            self.mark_health(feed_id, False)
            return []

    def fetch_all(self, feed_ids: list[str] | None = None) -> list[ObserveEvent]:
        ids = feed_ids if feed_ids is not None else self.ids()
        events: list[ObserveEvent] = []
        for fid in ids:
            events.extend(self.fetch(fid))
        return events


def default_registry() -> FeedRegistry:
    """Build registry with the three keyless adapters. Import-only; no network."""
    from .adapters.usgs_earthquakes import fetch as usgs_fetch
    from .adapters.gdelt import fetch as gdelt_fetch
    from .adapters.polymarket import fetch as poly_fetch

    reg = FeedRegistry()
    reg.register(
        "usgs_earthquakes",
        usgs_fetch,
        cadence_seconds=600,
        description="USGS GeoJSON earthquake feed (keyless)",
    )
    reg.register(
        "gdelt",
        gdelt_fetch,
        cadence_seconds=900,
        description="GDELT 2.0 Doc API world-event articles (keyless)",
    )
    reg.register(
        "polymarket",
        poly_fetch,
        cadence_seconds=300,
        description="Polymarket public markets API (keyless prediction odds)",
    )
    return reg
