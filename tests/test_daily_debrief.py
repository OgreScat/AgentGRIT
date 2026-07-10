"""Daily Debrief -- counts only what is in the logs; no invented spend."""

from pathlib import Path

from src.agents.daily_debrief_agent import build_debrief, render


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    import json
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_empty_logs_report_missing(tmp_path: Path):
    deb = build_debrief(day="2026-07-09", log_dir=tmp_path)
    assert deb.decision_count == 0
    assert "decisions.jsonl" in deb.missing_logs
    text = render(deb)
    assert "DAILY DEBRIEF" in text
    assert "2026-07-09" in text


def test_counts_dispositions_for_day(tmp_path: Path):
    _write_jsonl(tmp_path / "decisions.jsonl", [
        {"ts": "2026-07-09T10:00:00", "action": "summarize", "disposition": "proceed"},
        {"ts": "2026-07-09T11:00:00", "action": "is X safe", "disposition": "contested"},
        {"ts": "2026-07-08T09:00:00", "action": "old", "disposition": "proceed"},  # other day
        {"ts": "2026-07-09T12:00:00", "action": "rm -rf", "disposition": "refused"},
    ])
    _write_jsonl(tmp_path / "research_budget.jsonl", [
        {"date": "2026-07-09", "provider": "perplexity"},
        {"date": "2026-07-09", "provider": "grok"},
        {"date": "2026-07-08", "provider": "perplexity"},
    ])
    deb = build_debrief(day="2026-07-09", log_dir=tmp_path)
    assert deb.decision_count == 3
    assert deb.dispositions["proceed"] == 1
    assert deb.dispositions["contested"] == 1
    assert deb.dispositions["refused"] == 1
    assert deb.contested == ["is X safe"]
    assert deb.refused == ["rm -rf"]
    assert deb.research_paid == 2
    assert deb.research_providers["perplexity"] == 1
    assert deb.research_providers["grok"] == 1
    text = render(deb)
    assert "contested" in text
    assert "is X safe" in text
    assert "ATTENTION" in text
