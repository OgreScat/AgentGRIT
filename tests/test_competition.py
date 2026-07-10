"""Tests for in-house competition mode.

Pins the governance refusal (no safety-critical gamification), the two-contestant
minimum, deterministic scoring bounds, and correct ranking + logging. The local model
caller is monkeypatched so the tests never touch the network.
"""

import json

import pytest

from src.execution import competition as comp
from src.execution.competition import SafetyCriticalRefused, compete, default_score


def test_refuses_safety_critical():
    with pytest.raises(SafetyCriticalRefused):
        compete("apply the production migration", ["model-a", "model-b"],
                safety_critical=True)


def test_needs_two_contestants():
    with pytest.raises(ValueError):
        compete("task", ["only-one"])


def test_default_score_bounds():
    assert default_score("") == 0.0
    assert default_score("one") <= 0.1
    assert 0.0 <= default_score("a short but genuinely valid answer here") <= 1.0


def test_compete_ranks_and_logs(tmp_path, monkeypatch):
    outputs = {
        "model-a": "one two",  # tiny -> low score
        "model-b": " ".join(f"word{i}" for i in range(80)),  # substantive
    }
    monkeypatch.setattr(comp, "_ollama", lambda m, task, **k: outputs[m])
    log = tmp_path / "competition.jsonl"
    result = compete("summarize x", ["model-a", "model-b"], log_path=log)
    assert result["winner"] == "model-b"
    assert result["ranking"][0]["model"] == "model-b"
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["winner"] == "model-b"


def test_unresponsive_model_scores_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(
        comp, "_ollama",
        lambda m, task, **k: None if m == "dead" else "a good enough answer here now")
    result = compete("t", ["dead", "alive"], log_path=tmp_path / "c.jsonl")
    assert result["winner"] == "alive"
