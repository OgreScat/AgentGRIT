"""Task API honesty — orchestration endpoints must not fake execution state.

Requests authenticate through the existing fail-closed X-API-Key gate
(monkeypatched key). The gate itself staying fail-closed is asserted too.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import server

TEST_KEY = "test-honesty-key"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(server.settings, "api_secret_key", TEST_KEY, raising=False)
    c = TestClient(server.app, raise_server_exceptions=False)
    c.headers.update({"X-API-Key": TEST_KEY})
    return c


def test_auth_gate_still_fails_closed(monkeypatch):
    monkeypatch.setattr(server.settings, "api_secret_key", TEST_KEY, raising=False)
    bare = TestClient(server.app, raise_server_exceptions=False)
    assert bare.get("/tasks").status_code == 401


def test_spawn_returns_501_not_fake_queued(client):
    r = client.post("/tasks/spawn", json={"description": "do something"})
    assert r.status_code == 501
    body = str(r.json()).lower()
    assert "not enabled" in body or "not implemented" in body
    assert "queued" not in body


def test_get_task_returns_501_not_fake_running(client):
    r = client.get("/tasks/GRIT-20260101000000")
    assert r.status_code == 501
    assert "running" not in str(r.json()).lower()


def test_list_tasks_returns_501(client):
    r = client.get("/tasks")
    assert r.status_code == 501


def test_openapi_documents_501(client):
    spec = client.get("/openapi.json").json()
    spawn = spec["paths"]["/tasks/spawn"]["post"]
    assert "501" in spawn.get("responses", {})


def test_read_only_surfaces_still_work(client):
    assert client.get("/health").status_code == 200
    assert client.get("/console").status_code == 200
    assert client.get("/console/data?screen=overview").status_code == 200
