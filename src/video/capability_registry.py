"""Provider capability manifests — Class A/B/C, not product names."""

from __future__ import annotations

from .interfaces import AdapterManifest

# Order is cost-ish preference within a class; router still applies privacy.
DEFAULT_MANIFESTS: dict[str, AdapterManifest] = {
    "text_bundle": AdapterManifest(
        adapter_id="text_bundle",
        provider="local",
        model_class="C",
        supports_images=False,
        max_images=0,
        max_context_tokens=32_000,
        best_for=["summary", "transcript_qa"],
        forbidden_for=["temporal_visual"],
        certification_class="experimental",
        cloud=False,
    ),
    "ollama_vlm": AdapterManifest(
        adapter_id="ollama_vlm",
        provider="ollama",
        model_class="B",
        supports_images=True,
        max_images=8,
        max_context_tokens=16_000,
        best_for=["summary", "ui_code_screencast"],
        forbidden_for=[],
        certification_class="experimental",
        cloud=False,
    ),
    "anthropic_multimodal": AdapterManifest(
        adapter_id="anthropic_multimodal",
        provider="anthropic",
        model_class="A",
        supports_images=True,
        max_images=64,
        max_context_tokens=200_000,
        best_for=["temporal_visual", "summary", "ui_code_screencast"],
        certification_class="experimental",
        cloud=True,
    ),
    "openai_multimodal": AdapterManifest(
        adapter_id="openai_multimodal",
        provider="openai",
        model_class="A",
        supports_images=True,
        max_images=32,
        max_context_tokens=128_000,
        best_for=["temporal_visual", "summary"],
        certification_class="experimental",
        cloud=True,
    ),
    "google_multimodal": AdapterManifest(
        adapter_id="google_multimodal",
        provider="google",
        model_class="A",
        supports_images=True,
        max_images=64,
        max_context_tokens=200_000,
        best_for=["summary", "temporal_visual"],
        certification_class="experimental",
        cloud=True,
    ),
}


def get_manifest(adapter_id: str) -> AdapterManifest | None:
    return DEFAULT_MANIFESTS.get(adapter_id)


def list_manifests() -> list[AdapterManifest]:
    return list(DEFAULT_MANIFESTS.values())


def adapters_for_class(model_class: str, *, allow_cloud: bool) -> list[AdapterManifest]:
    out = []
    for m in DEFAULT_MANIFESTS.values():
        if m.model_class != model_class:
            continue
        if m.cloud and not allow_cloud:
            continue
        out.append(m)
    return out
