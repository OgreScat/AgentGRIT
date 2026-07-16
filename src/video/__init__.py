"""Video Capability Runtime — model-agnostic evidence plane (Phase 1 scaffold).

Deterministic media intelligence first; model adapters later.
See docs/VIDEO-CAPABILITY-RUNTIME.md.
"""

from .schema import VideoEvidenceBundle, bundle_from_dict, validate_bundle

__all__ = [
    "VideoEvidenceBundle",
    "bundle_from_dict",
    "validate_bundle",
]
