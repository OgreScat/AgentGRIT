"""Regression: router confidence normalization (postmortem 2026-07-03).

score_category once divided matched weight by the sum of ALL signal weights,
so no task could exceed ~0.1 confidence and every task routed to the
low-confidence fallback. Cost governance never engaged. These tests pin the
repaired behavior.
"""
from src.execution.router_v2 import TwoStageRouter, Provider


def test_simple_formatting_routes_to_ollama():
    d = TwoStageRouter().route("Format this Python code according to PEP8")
    assert d.provider == Provider.OLLAMA, d.reasoning
    assert not d.fallback_used, d.reasoning


def test_complex_architecture_routes_to_claude():
    d = TwoStageRouter().route("Design the architecture for a distributed caching system")
    assert d.provider.value.startswith("claude"), d.reasoning


def test_low_signal_still_falls_back():
    d = TwoStageRouter().route("Help me with this thing")
    assert d.fallback_used, d.reasoning
