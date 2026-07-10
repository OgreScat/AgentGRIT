"""
GRIT Eval Harness

Built directly on Anthropic's "Demystifying evals for AI agents" methodology.

The core distinctions we encode:
  - TRANSCRIPT (what the agent said/did) vs OUTCOME (final state of the world).
    We grade OUTCOMES wherever possible. An agent saying "routed correctly!"
    means nothing; the actual chosen model + actual cost is ground truth.
  - DETERMINISTIC graders for objective checks (model X was chosen, cost under Y).
  - LLM/JUDGMENT graders may return UNKNOWN when evidence is insufficient,
    instead of guessing. (We implement the UNKNOWN-capable grader interface even
    though GRIT's current graders are mostly deterministic — so adding a judge
    later needs no harness change.)
  - PARTIAL CREDIT composed across components, so "missed one requirement" is a
    visible failure mode, not a vague "felt off."
  - Evals are CI: the suite runs headless, returns a machine-readable report,
    and is the SOLE input that promotes/demotes GRIT's trust ladder.

This harness does NOT call any paid LLM. It exercises GRIT's own decision logic
(planner + governor) against fixed tasks with known-correct routing/verdicts.
That makes it free to run on every change and safe to run before sleep.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Callable


# ── Grading primitives ────────────────────────────────────────────────────────

class GradeStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"   # judge had insufficient evidence (Anthropic pattern)


@dataclass
class CheckResult:
    """One graded dimension of a task. Partial credit lives here."""
    dimension: str
    status: GradeStatus
    weight: float                 # contribution to the task score
    detail: str
    expected: Any = None
    actual: Any = None

    @property
    def credit(self) -> float:
        # UNKNOWN earns no credit but is not a hard fail of the task.
        return self.weight if self.status == GradeStatus.PASS else 0.0


@dataclass
class TaskResult:
    task_id: str
    description: str
    checks: list[CheckResult]
    duration_ms: float
    error: str | None = None

    @property
    def total_weight(self) -> float:
        return sum(c.weight for c in self.checks) or 1.0

    @property
    def score(self) -> float:
        """0.0–1.0 partial-credit score."""
        if self.error:
            return 0.0
        return sum(c.credit for c in self.checks) / self.total_weight

    @property
    def hard_failed(self) -> bool:
        """Any FAIL on a check marked critical (weight >= 1.0) = hard fail."""
        return self.error is not None or any(
            c.status == GradeStatus.FAIL and c.weight >= 1.0 for c in self.checks
        )

    @property
    def passed(self) -> bool:
        # A task passes if it scores >= 0.99 and did not hard-fail.
        return self.score >= 0.99 and not self.hard_failed


@dataclass
class SuiteReport:
    suite_name: str
    results: list[TaskResult]
    started_at: str
    duration_ms: float

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def mean_score(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.score for r in self.results) / len(self.results)

    @property
    def all_passed(self) -> bool:
        return self.pass_count == len(self.results) and len(self.results) > 0

    def to_dict(self) -> dict:
        return {
            "suite": self.suite_name,
            "started_at": self.started_at,
            "duration_ms": round(self.duration_ms, 1),
            "tasks_total": len(self.results),
            "tasks_passed": self.pass_count,
            "mean_score": round(self.mean_score, 4),
            "all_passed": self.all_passed,
            "results": [
                {
                    "task_id": r.task_id,
                    "description": r.description,
                    "score": round(r.score, 4),
                    "passed": r.passed,
                    "hard_failed": r.hard_failed,
                    "error": r.error,
                    "checks": [
                        {
                            "dimension": c.dimension,
                            "status": c.status.value,
                            "weight": c.weight,
                            "detail": c.detail,
                            "expected": _safe(c.expected),
                            "actual": _safe(c.actual),
                        }
                        for c in r.checks
                    ],
                }
                for r in self.results
            ],
        }

    def human_readable(self) -> str:
        lines = [
            f"EVAL SUITE: {self.suite_name}",
            "=" * 66,
            f"Tasks: {self.pass_count}/{len(self.results)} passed   "
            f"Mean score: {self.mean_score:.1%}   "
            f"({self.duration_ms:.0f} ms)",
            "-" * 66,
        ]
        for r in self.results:
            mark = "PASS" if r.passed else ("ERR " if r.error else "FAIL")
            lines.append(f"[{mark}] {r.task_id}  score={r.score:.0%}  — {r.description}")
            for c in r.checks:
                if c.status != GradeStatus.PASS:
                    sym = "?" if c.status == GradeStatus.UNKNOWN else "x"
                    lines.append(f"        {sym} {c.dimension}: {c.detail}")
            if r.error:
                lines.append(f"        ! error: {r.error}")
        lines.append("-" * 66)
        lines.append("RESULT: " + ("ALL PASSED ✅" if self.all_passed else "FAILURES PRESENT ❌"))
        return "\n".join(lines)


def _safe(v: Any) -> Any:
    """Make values JSON-serializable for the report."""
    if isinstance(v, (str, int, float, bool, type(None))):
        return v
    if isinstance(v, Enum):
        return v.value
    return str(v)


# ── Grader helpers (deterministic; UNKNOWN-capable interface) ─────────────────

def check_equals(dimension: str, expected: Any, actual: Any,
                 weight: float = 1.0) -> CheckResult:
    ok = expected == actual
    return CheckResult(
        dimension=dimension,
        status=GradeStatus.PASS if ok else GradeStatus.FAIL,
        weight=weight,
        detail="match" if ok else f"expected {expected!r}, got {actual!r}",
        expected=expected, actual=actual,
    )


def check_true(dimension: str, condition: bool, detail_pass: str,
               detail_fail: str, weight: float = 1.0) -> CheckResult:
    return CheckResult(
        dimension=dimension,
        status=GradeStatus.PASS if condition else GradeStatus.FAIL,
        weight=weight,
        detail=detail_pass if condition else detail_fail,
    )


def check_in(dimension: str, value: Any, allowed: set, weight: float = 1.0) -> CheckResult:
    ok = value in allowed
    return CheckResult(
        dimension=dimension,
        status=GradeStatus.PASS if ok else GradeStatus.FAIL,
        weight=weight,
        detail=f"{value!r} in {allowed}" if ok else f"{value!r} NOT in {allowed}",
        expected=allowed, actual=value,
    )


# ── Task definition ───────────────────────────────────────────────────────────

@dataclass
class EvalTask:
    """
    A fixed task with a grader. The grader receives nothing but the task input
    and returns a list of CheckResults — it computes GRIT's actual decision
    internally and grades the OUTCOME.
    """
    task_id: str
    description: str
    grader: Callable[[], list[CheckResult]]
    # The "pattern" this task belongs to, for trust-ladder bookkeeping.
    pattern: str = "general"


def run_task(task: EvalTask) -> TaskResult:
    start = time.perf_counter()
    try:
        checks = task.grader()
        err = None
    except Exception as e:  # a grader that throws is itself a failure
        checks = []
        err = f"{type(e).__name__}: {e}"
    dur = (time.perf_counter() - start) * 1000
    return TaskResult(task.task_id, task.description, checks, dur, err)


def run_suite(name: str, tasks: list[EvalTask]) -> SuiteReport:
    from datetime import datetime
    start = time.perf_counter()
    started = datetime.utcnow().isoformat()
    results = [run_task(t) for t in tasks]
    dur = (time.perf_counter() - start) * 1000
    return SuiteReport(name, results, started, dur)


def save_report(report: SuiteReport, path: str = "evals/last_report.json") -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report.to_dict(), indent=2))
    return str(p)
