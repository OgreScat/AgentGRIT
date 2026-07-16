"""Live retrieval helper — validated, role-profiled vault context for model calls.

`logos_system_for(task)` is the single governed entry point a call site uses.
It returns "" (never raises) unless ALL of the following hold:
- the vault is enabled + configured via environment;
- full fail-closed validation passes (pin consistency + every artifact sha256);
- the role profile selects at least one APPROVED artifact within budget.

The returned text is wrapped as UNTRUSTED reference context. It advises
reasoning; it can never authorize actions or override governance.

Role defaults to `grit_jr` (a local model is drone-tier); override with
GRIT_LOGOS_VAULT_ROLE for runtimes whose local model plays a bigger role.
"""
from __future__ import annotations

import os

from .config import load_config
from .profiles import load_bundle_text, select_for_role
from .validate import validate_vault

ENV_ROLE = "GRIT_LOGOS_VAULT_ROLE"
DEFAULT_ROLE = "grit_jr"


def logos_system_for(task: str = "", *, role: str | None = None) -> str:
    """Validated role bundle for the current runtime, or "" (fail-closed)."""
    try:
        cfg = load_config()
        if not cfg.configured:
            return ""
        report = validate_vault(cfg)
        if not report.valid or report.manifest is None:
            return ""
        use_role = (role or os.environ.get(ENV_ROLE, "") or DEFAULT_ROLE).strip().lower()
        selection = select_for_role(report.manifest, use_role)
        if not selection:
            return ""
        return load_bundle_text(cfg.path, selection, role=use_role)
    except Exception:  # noqa: BLE001 — retrieval must never break a model call
        return ""
