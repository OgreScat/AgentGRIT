"""Tests for JSONL log rotation -- bounds machine-layer exhaust so no log balloons.

Pins: a log over the cap rolls to .1; only LOG_KEEP archives are retained; a fresh log
under the cap is never rotated.
"""

from src.utils.logging import write_jsonl


def test_rotates_when_over_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_MAX_MB", "0.001")  # ~1 KB cap
    monkeypatch.setenv("LOG_KEEP", "3")
    for i in range(300):
        write_jsonl("t.jsonl", {"i": i, "pad": "x" * 60}, log_dir=tmp_path)
    assert (tmp_path / "t.jsonl").exists()
    assert (tmp_path / "t.jsonl.1").exists()


def test_keeps_only_n_rolls(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_MAX_MB", "0.001")
    monkeypatch.setenv("LOG_KEEP", "3")
    for i in range(800):
        write_jsonl("t.jsonl", {"i": i, "pad": "y" * 80}, log_dir=tmp_path)
    assert not (tmp_path / "t.jsonl.4").exists()
    assert (tmp_path / "t.jsonl.1").exists()


def test_small_log_not_rotated(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_MAX_MB", "5")
    for i in range(5):
        write_jsonl("t.jsonl", {"i": i}, log_dir=tmp_path)
    assert not (tmp_path / "t.jsonl.1").exists()
