"""Video query routing — capability class floor, privacy, refuse bad routes."""

from __future__ import annotations

import re

from .capability_registry import adapters_for_class, list_manifests
from .interfaces import RouteDecision
from .policy import allow_cloud, class_meets_floor, required_class_for_query
from .schema import VideoEvidenceBundle


def classify_query(query: str) -> str:
    """Cheap deterministic query class (not an LLM)."""
    q = (query or "").lower()
    if re.search(r"\b(secret|password|credential|api[_ -]?key|leak)\b", q):
        return "safety_sensitive"
    if re.search(r"\b(between|from)\s+\d|timestamp|at\s+\d{1,2}:\d{2}|what changed visually\b", q):
        return "temporal_visual"
    if re.search(r"\b(ui|button|terminal|code|screenshot|screencast|slide)\b", q):
        return "ui_code_screencast"
    if re.search(r"\b(summariz\w*|summary|tldr|overview|what is this (video|loom))\b", q):
        return "summary"
    return "transcript_qa"


def route(
    query: str,
    bundle: VideoEvidenceBundle,
    *,
    cloud_clearance: bool = False,
    prefer_local: bool = True,
) -> RouteDecision:
    """Pick cheapest class that can finish; refuse rather than silent truncate."""
    qclass = classify_query(query)
    floor = required_class_for_query(qclass)
    privacy_ok, privacy_why = allow_cloud(bundle, clearance=cloud_clearance)
    allow_cloud_flag = privacy_ok

    reasons = [f"query_class={qclass}", f"floor={floor}", privacy_why]

    # Spec (section 5): safety_sensitive — "no cloud without clearance".
    # The query itself signals possible secrets; bundle sensitivity alone
    # must not open a cloud route for it.
    if qclass == "safety_sensitive" and not cloud_clearance:
        allow_cloud_flag = False
        reasons.append("safety_sensitive: cloud disabled without explicit clearance")
    downgrades: list[str] = []

    # Caption-rich summary can stay Class C
    has_captions = bool(bundle.transcript) or bundle.source.captions_available
    if qclass == "summary" and has_captions:
        floor = "C"
        reasons.append("dense captions → Class C floor")

    # Vision required but no frames
    if floor in ("A", "B") and not bundle.frames and qclass in (
        "temporal_visual", "ui_code_screencast"
    ):
        return RouteDecision(
            query_class=qclass,
            chosen_class=floor,
            adapter_id=None,
            refuse=True,
            reasons=reasons + ["no frames in bundle — cannot answer visual query"],
            privacy=bundle.policy.privacy_boundary,
        )

    # Prefer C → B → A for cost
    order = ["C", "B", "A"]
    start = order.index(floor) if floor in order else 1
    for cls in order[start:]:
        cands = adapters_for_class(cls, allow_cloud=allow_cloud_flag)
        if prefer_local:
            local = [c for c in cands if not c.cloud]
            cands = local or cands
        if not cands:
            continue
        # Prefer non-cloud, then first registered
        cands = sorted(cands, key=lambda m: (m.cloud, m.adapter_id))
        pick = cands[0]
        if not class_meets_floor(pick.model_class, floor):
            continue
        if qclass in pick.forbidden_for:
            continue
        if pick.max_images < 8 and qclass == "temporal_visual":
            downgrades.append(f"max_images={pick.max_images}")
        return RouteDecision(
            query_class=qclass,
            chosen_class=pick.model_class,
            adapter_id=pick.adapter_id,
            refuse=False,
            reasons=reasons + [f"adapter={pick.adapter_id}"],
            downgrades=downgrades,
            privacy=bundle.policy.privacy_boundary,
        )

    return RouteDecision(
        query_class=qclass,
        chosen_class=floor,
        adapter_id=None,
        refuse=True,
        reasons=reasons + ["no certified adapter meets floor under privacy policy"],
        privacy=bundle.policy.privacy_boundary,
    )


def list_adapter_ids() -> list[str]:
    return sorted(m.adapter_id for m in list_manifests())
