"""Live vault smoke — the fixture-vs-reality gap, closed.

Skipped unless a real vault is configured. When one is, it MUST validate:
a vault mutation that leaves the live manifest unparseable fails here,
not in production. (Postmortem: v0.1.4 tail bytes broke the live vault
while fixture tests stayed green.)
"""
from __future__ import annotations

import os

import pytest

from src.logos_vault import validate_vault
from src.logos_vault.config import load_config


@pytest.mark.skipif(
    not os.environ.get("GRIT_LOGOS_VAULT_PATH"),
    reason="no live vault configured (set GRIT_LOGOS_VAULT_* to enable)",
)
def test_live_vault_validates():
    cfg = load_config()
    report = validate_vault(cfg)
    assert report.valid, report.failures
    assert report.total_count > 0
