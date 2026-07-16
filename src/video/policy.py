"""Privacy wall and cloud-clearance gates for video evidence."""

from __future__ import annotations

from .schema import VideoEvidenceBundle


def default_sensitivity_for_uri(uri: str) -> str:
    """Heuristic only — operator may override. Local paths default private."""
    u = (uri or "").lower()
    if u.startswith("file:") or u.startswith("/") or u.startswith("."):
        return "private"
    return "public"


def allow_cloud(bundle: VideoEvidenceBundle, *, clearance: bool = False) -> tuple[bool, str]:
    """Cloud multimodal/ASR only if not private or explicitly cleared."""
    if bundle.policy.sensitivity == "private" and not clearance:
        return False, "private sensitivity — local_only (privacy wall)"
    if bundle.policy.privacy_boundary == "local_only" and not clearance:
        return False, "privacy_boundary=local_only"
    if clearance:
        return True, "operator clearance"
    if bundle.policy.privacy_boundary == "cloud_cleared":
        return True, "bundle marked cloud_cleared"
    if bundle.policy.sensitivity == "public":
        return True, "public sensitivity"
    return False, "default refuse cloud"


def required_class_for_query(query_class: str) -> str:
    """Minimum model class letter (A > B > C)."""
    return {
        "summary": "C",
        "transcript_qa": "C",
        "temporal_visual": "B",
        "ui_code_screencast": "B",
        "safety_sensitive": "A",
    }.get(query_class, "B")


_CLASS_RANK = {"C": 0, "B": 1, "A": 2}


def class_meets_floor(chosen: str, floor: str) -> bool:
    return _CLASS_RANK.get(chosen, -1) >= _CLASS_RANK.get(floor, 99)
