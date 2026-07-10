"""
AgentGRIT Model Provenance Registry

Enforces which local (Ollama) models AgentGRIT is permitted to call, by
lineage. This exists because model provenance is a real governance
decision here — not a security boundary (local Ollama inference never
leaves the machine regardless of model origin) but a deliberate policy
about which model vendors AgentGRIT trusts enough to run at all.

This is a HARD gate, not a suggestion: _call_ollama() in router.py calls
is_model_approved() before every dispatch and refuses to call anything
not on the approved list, regardless of what OLLAMA_MODEL resolves to
from config/env. A stale or misconfigured default can no longer silently
route work to a forbidden model.

To approve a new local model: add it to APPROVED_MODELS with its real
lineage below. Do not approve a model you have not independently
verified the lineage of — see AgentGRIT-Provenance-Policy docs for the
verification standard this project holds itself to.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelLineage:
    model_id: str
    vendor: str
    lineage_notes: str
    approved: bool


# Verified lineage registry. "approved" reflects current AgentGRIT policy,
# not a technical judgment of model quality — a forbidden model can still
# be an excellent model.
MODEL_REGISTRY: dict[str, ModelLineage] = {
    "gemma4:12b": ModelLineage(
        model_id="gemma4:12b",
        vendor="Google DeepMind",
        lineage_notes="Gemma 4, Apache 2.0 license. Verified base model, no mixed lineage.",
        approved=True,
    ),
    "gemma4:26b": ModelLineage(
        model_id="gemma4:26b",
        vendor="Google DeepMind",
        lineage_notes="Gemma 4 MoE variant. Apache 2.0.",
        approved=True,
    ),
    "gemma4:31b": ModelLineage(
        model_id="gemma4:31b",
        vendor="Google DeepMind",
        lineage_notes="Gemma 4 dense variant. Apache 2.0.",
        approved=True,
    ),
    "qwen3-coder:30b": ModelLineage(
        model_id="qwen3-coder:30b",
        vendor="Alibaba Qwen team",
        lineage_notes="Forbidden by policy — not a quality judgment.",
        approved=False,
    ),
    "glm-4.7-flash:latest": ModelLineage(
        model_id="glm-4.7-flash:latest",
        vendor="Zhipu AI",
        lineage_notes="Forbidden by policy — not a quality judgment.",
        approved=False,
    ),
    "blendmodel:9b": ModelLineage(
        model_id="blendmodel:9b",
        vendor="ExampleVendor (mixed base + external post-training data)",
        lineage_notes="Mixed external post-training lineage. Forbidden by policy.",
        approved=False,
    ),
    "blendmodel:35b": ModelLineage(
        model_id="blendmodel:35b",
        vendor="ExampleVendor (mixed base + external post-training data)",
        lineage_notes="Mixed external post-training lineage. Forbidden by policy.",
        approved=False,
    ),
}

DEFAULT_APPROVED_MODEL = "gemma4:12b"


def is_model_approved(model_id: str) -> bool:
    """
    Returns True only if the model is both registered AND marked approved.
    Unregistered models are treated as NOT approved by default — an
    unknown model is a policy gap to close, not a pass.
    """
    entry = MODEL_REGISTRY.get(model_id)
    return entry.approved if entry else False


def explain(model_id: str) -> str:
    """Human-readable reason for a model's approval status, for logging."""
    entry = MODEL_REGISTRY.get(model_id)
    if entry is None:
        return f"'{model_id}' is not in the provenance registry — treated as forbidden until added."
    status = "approved" if entry.approved else "forbidden"
    return f"'{model_id}' ({entry.vendor}) is {status}: {entry.lineage_notes}"
