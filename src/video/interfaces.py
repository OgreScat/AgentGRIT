"""Protocols for the video capability runtime (model-agnostic)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .schema import ExtractionPolicy, FrameRef, SourceInfo, TranscriptUtterance, VideoEvidenceBundle


@dataclass
class SourceMedia:
    """Local media handle after acquisition."""
    path: Path
    uri: str
    checksum_sha256: str = ""
    duration_s: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterManifest:
    """What a consumer can actually take — capability class, not marketing name."""

    adapter_id: str
    provider: str
    model_class: str  # A | B | C
    supports_images: bool
    max_images: int
    max_context_tokens: int
    supports_audio: bool = False
    supports_tool_use: bool = False
    best_for: list[str] = field(default_factory=list)
    forbidden_for: list[str] = field(default_factory=list)
    certification_class: str = "experimental"  # experimental | needswork | approved
    cloud: bool = False


@dataclass
class ModelPacket:
    """Adapter-specific projection of a bundle (prompt + optional image paths)."""

    adapter_id: str
    text: str
    image_paths: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelAnswer:
    text: str
    cited_frame_ids: list[str] = field(default_factory=list)
    cited_t_ranges: list[tuple[float, float]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    self_certified: bool = False  # always treat as untrusted; governance grades


@dataclass
class RouteDecision:
    query_class: str
    chosen_class: str
    adapter_id: str | None
    refuse: bool
    reasons: list[str] = field(default_factory=list)
    downgrades: list[str] = field(default_factory=list)
    privacy: str = "local_only"

    def render(self) -> str:
        lines = [
            "ROUTE",
            f"  query_class: {self.query_class}",
            f"  chosen_class: {self.chosen_class}",
            f"  adapter: {self.adapter_id or 'none'}",
            f"  refuse: {str(self.refuse).lower()}",
            f"  privacy: {self.privacy}",
        ]
        if self.reasons:
            lines.append(f"  reasons: {self.reasons}")
        if self.downgrades:
            lines.append(f"  downgrades: {self.downgrades}")
        return "\n".join(lines)


@runtime_checkable
class MediaIngest(Protocol):
    def acquire(self, uri: str, *, cache_dir: Path) -> SourceMedia: ...


@runtime_checkable
class FrameExtractor(Protocol):
    def extract(
        self, media: SourceMedia, policy: ExtractionPolicy
    ) -> list[FrameRef]: ...


@runtime_checkable
class TranscriptProvider(Protocol):
    def transcribe(self, media: SourceMedia) -> list[TranscriptUtterance]: ...


@runtime_checkable
class BundleBuilder(Protocol):
    def build(
        self,
        media: SourceMedia,
        frames: list[FrameRef],
        transcript: list[TranscriptUtterance],
        *,
        policy_sensitivity: str = "public",
    ) -> VideoEvidenceBundle: ...


@runtime_checkable
class ModelAdapter(Protocol):
    manifest: AdapterManifest

    def project(self, bundle: VideoEvidenceBundle, query: str) -> ModelPacket: ...

    def invoke(self, packet: ModelPacket) -> ModelAnswer: ...


@runtime_checkable
class VideoRouter(Protocol):
    def route(self, query: str, bundle: VideoEvidenceBundle) -> RouteDecision: ...
