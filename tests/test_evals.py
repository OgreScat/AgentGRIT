"""Tests for the eval harness — the harness must itself be trustworthy."""

from src.evals.harness import (
    run_suite, GradeStatus, check_equals, check_true, check_in,
    CheckResult, TaskResult, EvalTask,
)
from src.evals.suite import get_suite


def test_suite_runs_green():
    report = run_suite("test", get_suite())
    assert report.all_passed, report.human_readable()
    assert report.mean_score == 1.0


def test_partial_credit_math():
    checks = [
        check_true("a", True, "ok", "no", weight=1.0),
        check_true("b", False, "ok", "no", weight=1.0),
    ]
    r = TaskResult("t", "d", checks, 0.0)
    assert r.score == 0.5  # one of two equal-weight checks passed


def test_hard_fail_on_critical_check():
    checks = [check_true("crit", False, "ok", "no", weight=2.0)]
    r = TaskResult("t", "d", checks, 0.0)
    assert r.hard_failed
    assert not r.passed


def test_unknown_earns_no_credit_but_not_hard_fail():
    c = CheckResult("dim", GradeStatus.UNKNOWN, 1.0, "insufficient evidence")
    r = TaskResult("t", "d", [c], 0.0)
    assert c.credit == 0.0
    assert not r.hard_failed  # UNKNOWN is not a FAIL
    assert not r.passed       # but task isn't fully passed either


def test_grader_exception_becomes_error():
    def boom():
        raise ValueError("kaboom")
    from src.evals.harness import run_task
    r = run_task(EvalTask("x", "explodes", boom))
    assert r.error is not None
    assert "kaboom" in r.error
    assert r.score == 0.0


def test_report_is_json_serializable():
    import json
    report = run_suite("test", get_suite())
    json.dumps(report.to_dict())  # must not raise
