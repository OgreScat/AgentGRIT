"""VideoEvidenceBundle v1 — canonical, versioned evidence (not a prompt)."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = "1.0"


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass
class SourceInfo:
    uri: str
    checksum_sha256: str = ""
    duration_s: float = 0.0
    codec: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    acquisition: str = "unknown"  # local_copy | yt_dlp | fixture
    captions_available: bool = False


@dataclass
class PolicyInfo:
    sensitivity: str = "public"  # public | internal | private
    privacy_boundary: str = "local_only"  # local_only | cloud_cleared
    allowed_model_classes: list[str] = field(default_factory=lambda: ["A", "B", "C"])
    retention: str = "session"


@dataclass
class Segment:
    start_s: float
    end_s: float
    shot_type: str = "unknown"
    motion_score: float = 0.0
    speech_density: float = 0.0
    ocr_density: float = 0.0


@dataclass
class FrameRef:
    frame_id: str
    t_s: float
    path: str = ""
    thumb_hash: str = ""
    ocr_text: str = ""
    visual_tags: list[str] = field(default_factory=list)
    dedup_parent: str | None = None


@dataclass
class TranscriptUtterance:
    t_start_s: float
    t_end_s: float
    text: str
    speaker: str | None = None
    source: str = "none"  # native_caption | whisper_local | whisper_cloud | none
    confidence: float = 0.0


@dataclass
class Entity:
    entity_id: str
    kind: str  # speaker | ui | product | code | slide
    label: str
    t_start_s: float | None = None
    t_end_s: float | None = None
    frame_ids: list[str] = field(default_factory=list)


@dataclass
class Provenance:
    tools: list[dict[str, str]] = field(default_factory=list)
    commands: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


@dataclass
class FocusWindow:
    start_s: float | None = None
    end_s: float | None = None
    timestamps: list[float] = field(default_factory=list)


@dataclass
class ExtractionPolicy:
    mode: str = "balanced"  # sparse | balanced | dense | custom
    max_frames: int = 48
    dedup: bool = True


@dataclass
class VideoEvidenceBundle:
    """Canonical video evidence. Downstream adapters project; they do not redefine."""

    source: SourceInfo
    schema_version: str = SCHEMA_VERSION
    bundle_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=_now)
    policy: PolicyInfo = field(default_factory=PolicyInfo)
    segments: list[Segment] = field(default_factory=list)
    frames: list[FrameRef] = field(default_factory=list)
    transcript: list[TranscriptUtterance] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    indexes: dict[str, Any] = field(default_factory=lambda: {
        "keywords": [],
        "topic_windows": [],
        "frame_text_crosswalk": [],
    })
    provenance: Provenance = field(default_factory=Provenance)
    focus: FocusWindow = field(default_factory=FocusWindow)
    extraction_policy: ExtractionPolicy = field(default_factory=ExtractionPolicy)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def write_json(self, path: str | Any) -> None:
        from pathlib import Path
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json(), encoding="utf-8")


def bundle_from_dict(data: dict[str, Any]) -> VideoEvidenceBundle:
    """Best-effort hydrate (Phase 1 — strict only on required source.uri)."""
    src = data.get("source") or {}
    source = SourceInfo(
        uri=str(src.get("uri") or ""),
        checksum_sha256=str(src.get("checksum_sha256") or ""),
        duration_s=float(src.get("duration_s") or 0),
        codec=str(src.get("codec") or ""),
        width=int(src.get("width") or 0),
        height=int(src.get("height") or 0),
        fps=float(src.get("fps") or 0),
        acquisition=str(src.get("acquisition") or "unknown"),
        captions_available=bool(src.get("captions_available")),
    )
    pol = data.get("policy") or {}
    policy = PolicyInfo(
        sensitivity=str(pol.get("sensitivity") or "public"),
        privacy_boundary=str(pol.get("privacy_boundary") or "local_only"),
        allowed_model_classes=list(pol.get("allowed_model_classes") or ["A", "B", "C"]),
        retention=str(pol.get("retention") or "session"),
    )
    segments = [
        Segment(
            start_s=float(s.get("start_s") or 0),
            end_s=float(s.get("end_s") or 0),
            shot_type=str(s.get("shot_type") or "unknown"),
            motion_score=float(s.get("motion_score") or 0),
            speech_density=float(s.get("speech_density") or 0),
            ocr_density=float(s.get("ocr_density") or 0),
        )
        for s in (data.get("segments") or [])
        if isinstance(s, dict)
    ]
    frames = [
        FrameRef(
            frame_id=str(f.get("frame_id") or ""),
            t_s=float(f.get("t_s") or 0),
            path=str(f.get("path") or ""),
            thumb_hash=str(f.get("thumb_hash") or ""),
            ocr_text=str(f.get("ocr_text") or ""),
            visual_tags=list(f.get("visual_tags") or []),
            dedup_parent=f.get("dedup_parent"),
        )
        for f in (data.get("frames") or [])
        if isinstance(f, dict) and f.get("frame_id")
    ]
    transcript = [
        TranscriptUtterance(
            t_start_s=float(t.get("t_start_s") or 0),
            t_end_s=float(t.get("t_end_s") or 0),
            text=str(t.get("text") or ""),
            speaker=t.get("speaker"),
            source=str(t.get("source") or "none"),
            confidence=float(t.get("confidence") or 0),
        )
        for t in (data.get("transcript") or [])
        if isinstance(t, dict)
    ]
    prov_raw = data.get("provenance") or {}
    provenance = Provenance(
        tools=list(prov_raw.get("tools") or []),
        commands=list(prov_raw.get("commands") or []),
        warnings=list(prov_raw.get("warnings") or []),
        missing=list(prov_raw.get("missing") or []),
    )
    foc = data.get("focus") or {}
    focus = FocusWindow(
        start_s=foc.get("start_s"),
        end_s=foc.get("end_s"),
        timestamps=list(foc.get("timestamps") or []),
    )
    ep = data.get("extraction_policy") or {}
    extraction_policy = ExtractionPolicy(
        mode=str(ep.get("mode") or "balanced"),
        max_frames=int(ep.get("max_frames") or 48),
        dedup=bool(ep.get("dedup", True)),
    )
    return VideoEvidenceBundle(
        source=source,
        schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
        bundle_id=str(data.get("bundle_id") or str(uuid.uuid4())),
        created_at=str(data.get("created_at") or _now()),
        policy=policy,
        segments=segments,
        frames=frames,
        transcript=transcript,
        entities=[],  # Phase 2+
        indexes=dict(data.get("indexes") or {"keywords": [], "topic_windows": [], "frame_text_crosswalk": []}),
        provenance=provenance,
        focus=focus,
        extraction_policy=extraction_policy,
    )


def validate_bundle(bundle: VideoEvidenceBundle) -> list[str]:
    """Return list of problems (empty = valid enough for Phase 1)."""
    errs: list[str] = []
    if not bundle.source.uri:
        errs.append("source.uri required")
    if bundle.schema_version != SCHEMA_VERSION:
        errs.append(f"unsupported schema_version {bundle.schema_version}")
    if bundle.policy.sensitivity not in ("public", "internal", "private"):
        errs.append("policy.sensitivity invalid")
    if bundle.policy.privacy_boundary not in ("local_only", "cloud_cleared"):
        errs.append("policy.privacy_boundary invalid")
    for f in bundle.frames:
        if not f.frame_id:
            errs.append("frame missing frame_id")
    # Honesty: frames without any OCR text must declare "ocr" in provenance.missing
    if bundle.frames and not any(f.ocr_text for f in bundle.frames):
        if "ocr" not in bundle.provenance.missing:
            errs.append("frames lack OCR text but provenance.missing does not declare 'ocr'")
    return errs
