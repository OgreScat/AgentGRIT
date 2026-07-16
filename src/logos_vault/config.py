"""Logos Vault configuration — disabled by default, explicit opt-in, local only."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_ENABLED = "GRIT_LOGOS_VAULT_ENABLED"
ENV_PATH = "GRIT_LOGOS_VAULT_PATH"
ENV_PIN = "GRIT_LOGOS_VAULT_PIN"

PIN_FILENAME = ".grit-vault-pin"
MANIFEST_FILENAME = "vault-manifest.json"


@dataclass
class LogosVaultConfig:
    enabled: bool = False
    path: Path | None = None
    pin: str = ""

    @property
    def configured(self) -> bool:
        return self.enabled and self.path is not None and bool(self.pin)


def load_config(env: dict[str, str] | None = None) -> LogosVaultConfig:
    """Read config from environment. Never raises; fail-closed defaults."""
    e = env if env is not None else dict(os.environ)
    enabled = str(e.get(ENV_ENABLED, "")).strip().lower() in ("1", "true", "yes", "on")
    raw_path = str(e.get(ENV_PATH, "")).strip()
    pin = str(e.get(ENV_PIN, "")).strip()
    path = Path(raw_path).expanduser() if raw_path else None
    return LogosVaultConfig(enabled=enabled, path=path, pin=pin)
