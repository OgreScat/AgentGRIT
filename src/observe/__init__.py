"""GRIT Observe — governed live-data observation layer (v0).

Adapters fetch keyless public feeds; fuse scores freshness + corroboration;
gate runs research_quality.assess and refuses actionability for stale/contested
signals. Observation NEVER acts — scored evidence only.
"""

from .schema import ObserveEvent
from .registry import FeedRegistry, default_registry

__all__ = ["ObserveEvent", "FeedRegistry", "default_registry"]
