"""Tests for the API-key auth gate -- the fix for the unauthenticated-endpoint finding.

Pins: /health stays open; a loopback host with no key is allowed (local dev); a
non-loopback host with no key is REFUSED (fail closed); a configured key is required
and constant-time compared. The dependency is unit-tested directly (no TestClient /
lifespan needed).
"""

import asyncio
import types

import pytest
from fastapi import HTTPException

from src.api import server


def _req(path="/tasks/spawn"):
    return types.SimpleNamespace(url=types.SimpleNamespace(path=path))


def _call(req, key=None):
    return asyncio.run(server.require_api_key(req, key))


def test_health_always_open(monkeypatch):
    monkeypatch.setattr(server.settings, "api_secret_key", "", raising=False)
    monkeypatch.setattr(server.settings, "api_host", "0.0.0.0", raising=False)
    assert _call(_req("/health")) is None


def test_loopback_no_key_allowed(monkeypatch):
    monkeypatch.setattr(server.settings, "api_secret_key", "", raising=False)
    monkeypatch.setattr(server.settings, "api_host", "127.0.0.1", raising=False)
    assert _call(_req("/tasks/spawn")) is None


def test_exposed_without_key_is_refused(monkeypatch):
    monkeypatch.setattr(server.settings, "api_secret_key", "", raising=False)
    monkeypatch.setattr(server.settings, "api_host", "0.0.0.0", raising=False)
    with pytest.raises(HTTPException) as e:
        _call(_req("/tasks/spawn"))
    assert e.value.status_code == 503


def test_key_required_when_configured(monkeypatch):
    monkeypatch.setattr(server.settings, "api_secret_key", "s3cr3t-key-value-1234", raising=False)
    monkeypatch.setattr(server.settings, "api_host", "0.0.0.0", raising=False)
    with pytest.raises(HTTPException) as e:
        _call(_req("/tasks/spawn"), key=None)
    assert e.value.status_code == 401


def test_wrong_key_rejected(monkeypatch):
    monkeypatch.setattr(server.settings, "api_secret_key", "s3cr3t-key-value-1234", raising=False)
    monkeypatch.setattr(server.settings, "api_host", "0.0.0.0", raising=False)
    with pytest.raises(HTTPException) as e:
        _call(_req("/tasks/spawn"), key="wrong-key")
    assert e.value.status_code == 401


def test_correct_key_passes(monkeypatch):
    monkeypatch.setattr(server.settings, "api_secret_key", "s3cr3t-key-value-1234", raising=False)
    monkeypatch.setattr(server.settings, "api_host", "0.0.0.0", raising=False)
    assert _call(_req("/tasks/spawn"), key="s3cr3t-key-value-1234") is None
