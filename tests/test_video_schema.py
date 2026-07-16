"""Phase 1 video capability runtime — offline schema + router tests."""

from __future__ import annotations

import json
from pathlib import Path

from src.video.pipeline import build_from_fixture
from src.video.policy import allow_cloud, required_class_for_query
from src.video.router import classify_query, route
from src.video.schema import validate_bundle, bundle_from_dict, SCHEMA_VERSION

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "video" / "sample_manifest.json"


def test_fixture_bundle_valid():
    bundle = build_from_fixture(FIXTURE)
    assert bundle.schema_version == SCHEMA_VERSION
    assert bundle.source.uri.startswith("fixture://")
    assert len(bundle.frames) == 2
    assert len(bundle.transcript) == 2
    errs = validate_bundle(bundle)
    assert errs == []


def test_roundtrip_dict():
    bundle = build_from_fixture(FIXTURE)
    data = bundle.to_dict()
    b2 = bundle_from_dict(data)
    assert b2.bundle_id == bundle.bundle_id
    assert b2.frames[0].frame_id == "f0001"


def test_validate_requires_uri():
    bundle = build_from_fixture(FIXTURE)
    bundle.source.uri = ""
    assert "source.uri required" in validate_bundle(bundle)


def test_classify_query():
    assert classify_query("summarize this loom") == "summary"
    assert classify_query("what changed visually between 02:10 and 02:18") == "temporal_visual"
    assert classify_query("is there a password leak in the UI") == "safety_sensitive"
    assert classify_query("what does the terminal show") == "ui_code_screencast"


def test_route_summary_prefers_class_c_with_captions():
    bundle = build_from_fixture(FIXTURE)
    d = route("summarize this video", bundle, prefer_local=True)
    assert d.refuse is False
    assert d.chosen_class == "C"
    assert d.adapter_id == "text_bundle"


def test_route_temporal_needs_vision_class():
    bundle = build_from_fixture(FIXTURE)
    d = route("what changed visually at 00:16", bundle, prefer_local=True, cloud_clearance=False)
    assert d.refuse is False
    # local ollama_vlm Class B
    assert d.chosen_class in ("B", "A")
    assert d.adapter_id in ("ollama_vlm", "anthropic_multimodal", "openai_multimodal", "google_multimodal")


def test_route_refuses_visual_without_frames():
    bundle = build_from_fixture(FIXTURE)
    bundle.frames = []
    d = route("what changed visually between 1 and 2", bundle)
    assert d.refuse is True
    assert any("no frames" in r for r in d.reasons)


def test_privacy_wall_blocks_cloud_for_private():
    bundle = build_from_fixture(FIXTURE)
    bundle.policy.sensitivity = "private"
    bundle.policy.privacy_boundary = "local_only"
    ok, why = allow_cloud(bundle, clearance=False)
    assert ok is False
    assert "private" in why or "local_only" in why
    d = route("summarize", bundle, cloud_clearance=False)
    # text_bundle is local Class C — still OK for summary
    assert d.refuse is False
    assert d.adapter_id == "text_bundle"


def test_required_class_floor():
    assert required_class_for_query("summary") == "C"
    assert required_class_for_query("temporal_visual") == "B"


def test_route_safety_sensitive_refuses_cloud_without_clearance():
    """Spec section 5: no cloud for safety_sensitive without explicit clearance."""
    bundle = build_from_fixture(FIXTURE)
    d = route("is there a password leak in the UI", bundle, cloud_clearance=False)
    assert d.query_class == "safety_sensitive"
    assert d.refuse is True
    assert any("clearance" in r for r in d.reasons)


def test_route_safety_sensitive_allows_cloud_with_clearance():
    bundle = build_from_fixture(FIXTURE)
    d = route("is there a password leak in the UI", bundle, cloud_clearance=True)
    assert d.refuse is False
    assert d.chosen_class == "A"


def test_sha256_is_full_file(tmp_path):
    import hashlib
    from src.video.pipeline import _sha256_file
    p = tmp_path / "blob.bin"
    p.write_bytes(b"x" * 3_000_000)
    assert _sha256_file(p) == hashlib.sha256(b"x" * 3_000_000).hexdigest()
