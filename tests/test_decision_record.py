"""Tests for the Decision Record surface -- the auditable "why".

Proves disposition is derived correctly from REAL upstream objects
(BylawResult + Assessment), that cheaper alternatives are honest, that the
record persists fail-safe, and that render() is human-readable.
"""

from src.governance.decision_record import (
    Disposition, cheaper_alternatives, compose, record,
)
from src.governance.bylaws import BylawResult, BylawAction
from src.governance.research_quality import Assessment, Verdict


class _Routing:
    provider = "ollama"
    category = "research"
    confidence = 0.82
    estimated_cost = 0.0
    reason = "local model capable; cheapest tier"


def test_cheaper_alternatives_lists_only_cheaper():
    costs = {"ollama": 0.0, "perplexity": 0.001, "grok": 0.002, "claude-opus": 0.015}
    alts = cheaper_alternatives("grok", costs)
    names = [a["provider"] for a in alts]
    assert names == ["ollama", "perplexity"]          # strictly cheaper, sorted
    assert all("not selected by capability" in a["why_not"] for a in alts)


def test_unknown_chosen_yields_no_alternatives():
    assert cheaper_alternatives("mystery", {"ollama": 0.0}) == []


def test_block_is_refused():
    rec = compose("rm -rf build/",
                  bylaw=BylawResult(action=BylawAction.BLOCK, reason="destructive"))
    assert rec.disposition is Disposition.REFUSED
    assert "destructive" in rec.rationale


def test_contested_evidence_is_contested():
    ev = Assessment(Verdict.CONTESTED, 0.8, "sources disagree", require_human=True)
    rec = compose("is X safe", routing=_Routing(),
                  bylaw=BylawResult(action=BylawAction.PROCEED, reason="read-only"),
                  evidence=ev)
    assert rec.disposition is Disposition.CONTESTED
    assert "disagree" in rec.rationale


def test_escalate_bylaw_is_escalated():
    rec = compose("publish page",
                  bylaw=BylawResult(action=BylawAction.ESCALATE, reason="irreversible external"))
    assert rec.disposition is Disposition.ESCALATED


def test_require_human_evidence_escalates_even_when_bylaw_proceeds():
    ev = Assessment(Verdict.SUFFICIENT, 0.7, "reversible high-stakes", require_human=True)
    rec = compose("spend budget", routing=_Routing(),
                  bylaw=BylawResult(action=BylawAction.PROCEED, reason="ok"),
                  evidence=ev)
    assert rec.disposition is Disposition.ESCALATED


def test_clean_proceed():
    ev = Assessment(Verdict.SUFFICIENT, 0.9, "corroborated", require_human=False)
    rec = compose("summarize reviews", routing=_Routing(),
                  bylaw=BylawResult(action=BylawAction.PROCEED, reason="safe"),
                  evidence=ev)
    assert rec.disposition is Disposition.PROCEED
    assert rec.chosen_provider == "ollama"


def test_block_wins_over_contested():
    # a hard block must dominate even a source conflict
    ev = Assessment(Verdict.CONTESTED, 0.8, "disagree", require_human=True)
    rec = compose("dangerous", bylaw=BylawResult(action=BylawAction.BLOCK, reason="law-0"),
                  evidence=ev)
    assert rec.disposition is Disposition.REFUSED


def test_record_persists_and_returns(tmp_path, monkeypatch):
    written = {}

    def fake_write(name, entry, *a, **k):
        written["name"], written["entry"] = name, entry
        return True

    monkeypatch.setattr("src.utils.logging.write_jsonl", fake_write)
    rec = record("do a thing", routing=_Routing(),
                 bylaw=BylawResult(action=BylawAction.PROCEED, reason="ok"))
    assert written["name"] == "decisions.jsonl"
    assert written["entry"]["disposition"] == "proceed"
    assert rec.disposition is Disposition.PROCEED


def test_record_is_failsafe(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk gone")

    monkeypatch.setattr("src.utils.logging.write_jsonl", boom)
    # must not raise -- audit-write failure can never break the caller's flow
    rec = record("x", bylaw=BylawResult(action=BylawAction.PROCEED, reason="ok"))
    assert rec.disposition is Disposition.PROCEED


def test_render_is_human_readable():
    ev = Assessment(Verdict.SUFFICIENT, 0.86, "corroborated", require_human=False)
    text = compose("summarize competitor reviews", routing=_Routing(),
                   bylaw=BylawResult(action=BylawAction.PROCEED, reason="read-only"),
                   evidence=ev,
                   alternatives=cheaper_alternatives("perplexity",
                                                     {"ollama": 0.0, "perplexity": 0.001}),
                   authorized_by="trust:autonomous", project="demo").render()
    assert "DECISION RECORD" in text
    assert "PROCEED" in text
    assert "ollama" in text
    assert "authorized by: trust:autonomous" in text


def test_to_entry_has_no_invented_fields():
    rec = compose("x", bylaw=BylawResult(action=BylawAction.PROCEED, reason="ok"))
    entry = rec.to_entry()
    # routing was not supplied -> those fields are honestly None, not fabricated
    assert entry["chosen_provider"] is None
    assert entry["estimated_cost_usd"] is None
    assert entry["disposition"] == "proceed"
