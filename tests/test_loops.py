"""Tests for governed loops -- cadence logic + the trust-ceiling contract.

Pins: interval and daily-at scheduling (including catch-up), the disabled short-circuit,
and the core governance rule -- a loop cannot auto-run an action above its trust ceiling.
"""

from datetime import datetime, timedelta

from src.execution.loops import Loop, Trust, can_autorun, due_loops, is_due, load


def _now(h, m):
    return datetime(2026, 7, 8, h, m, 0)


def test_interval_due_when_never_run():
    lp = Loop(name="x", every_seconds=60)
    assert is_due(lp, _now(9, 0), last=None) is True


def test_interval_not_due_when_recent():
    lp = Loop(name="x", every_seconds=60)
    assert is_due(lp, _now(9, 0), last=_now(9, 0) - timedelta(seconds=30)) is False


def test_interval_due_when_elapsed():
    lp = Loop(name="x", every_seconds=60)
    assert is_due(lp, _now(9, 0), last=_now(9, 0) - timedelta(seconds=120)) is True


def test_daily_due_at_exact_minute():
    lp = Loop(name="x", at="03:00")
    assert is_due(lp, _now(3, 0), last=None) is True


def test_daily_not_double_fire_same_minute():
    lp = Loop(name="x", at="03:00")
    assert is_due(lp, _now(3, 0), last=_now(3, 0)) is False


def test_daily_catch_up_if_missed_today():
    lp = Loop(name="x", at="03:00")
    assert is_due(lp, _now(9, 0), last=_now(3, 0) - timedelta(days=1)) is True


def test_daily_not_due_before_time():
    lp = Loop(name="x", at="03:00")
    assert is_due(lp, _now(2, 0), last=_now(3, 0) - timedelta(days=1)) is False


def test_disabled_never_due():
    lp = Loop(name="x", every_seconds=1, enabled=False)
    assert is_due(lp, _now(9, 0), last=None) is False


def test_ceiling_allows_up_to_declared():
    lp = Loop(name="x", trust_ceiling=Trust.MEDIUM)
    assert can_autorun(lp, Trust.LOW) is True
    assert can_autorun(lp, Trust.MEDIUM) is True


def test_ceiling_blocks_above_declared():
    lp = Loop(name="x", trust_ceiling=Trust.MEDIUM)
    assert can_autorun(lp, Trust.HIGH) is False
    assert can_autorun(lp, Trust.CRITICAL) is False


def test_load_parses_and_defaults(tmp_path):
    p = tmp_path / "loops.json"
    p.write_text('[{"name":"g","at":"03:00","trust_ceiling":"medium"},'
                 ' {"name":"h","every_seconds":300}]')
    loops = load(p)
    assert [lp.name for lp in loops] == ["g", "h"]
    assert loops[0].trust_ceiling is Trust.MEDIUM
    assert loops[1].trust_ceiling is Trust.LOW  # default


def test_due_loops_filters():
    loops = [Loop(name="a", every_seconds=60), Loop(name="b", at="03:00", enabled=False)]
    due = due_loops(loops, now=_now(3, 0))
    assert [lp.name for lp in due] == ["a"]
