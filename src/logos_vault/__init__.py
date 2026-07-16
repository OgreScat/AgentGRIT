"""Logos Vault — governed shared reasoning-corpus consumer (contract + local retrieval).

The Logos Vault is a private, versioned library of curated reasoning playbooks,
routing rubrics, operating methods, evals, and model profiles shared across
GRIT-family projects. This package is the CONSUMER contract:

- disabled by default; explicit opt-in via environment;
- local path only; no network, no Git actions, no model calls;
- fail-closed validation (pin consistency + per-artifact sha256 integrity);
- role-profiled selection (GRIT JR / GRIT / GRIT GM) of APPROVED artifacts only;
- retrieved text is wrapped as UNTRUSTED reference context, never authority.

Vault content can never authorize actions, override bylaws/trust tiers, or
bypass audit. Governance always outranks vault artifacts.
"""
from .config import LogosVaultConfig, load_config
from .schema import (
    AdmissionState,
    LogosArtifact,
    LogosManifest,
    ValidationFailure,
    ValidationReport,
)
from .validate import validate_vault
from .profiles import ROLE_PROFILES, select_for_role, load_bundle_text, UNTRUSTED_BANNER

__all__ = [
    "LogosVaultConfig",
    "load_config",
    "AdmissionState",
    "LogosArtifact",
    "LogosManifest",
    "ValidationFailure",
    "ValidationReport",
    "validate_vault",
    "ROLE_PROFILES",
    "select_for_role",
    "load_bundle_text",
    "UNTRUSTED_BANNER",
]
