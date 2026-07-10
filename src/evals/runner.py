"""
GRIT Eval Runner

The bridge that turns eval OUTCOMES into trust-ladder movement. This is what
makes GRIT's autonomy *earned* rather than asserted: a pattern only graduates
UNTRUSTED -> TRUSTED -> AUTONOMOUS by passing its evals repeatedly, and any
eval failure demotes it. No counter ticks up on faith.

Usage:
    python -m src.evals.runner            # run suite, print report, update trust
    python -m src.evals.runner --no-trust # run suite only, don't touch trust
    python -m src.evals.runner --json     # machine-readable for CI

Exit code is 0 only if every task passed — so this doubles as a CI gate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from src.evals.harness import run_suite, save_report, SuiteReport
from src.evals.suite import get_suite


async def _apply_to_trust(report: SuiteReport) -> list[str]:
    """
    Feed per-task outcomes into the trust manager, grouped by pattern.
    A pattern is recorded as success only if ALL its tasks passed this run;
    any failure in the pattern records a failure (and demotes).
    Returns human-readable trust-change notes.
    """
    try:
        from src.governance.trust import get_trust_manager
    except Exception as e:  # trust module needs pydantic; degrade gracefully
        return [f"(trust update skipped: {type(e).__name__}: {e})"]

    tm = get_trust_manager()

    # Group results by pattern.
    by_pattern: dict[str, list] = {}
    # We need the pattern for each task; rebuild the map from the suite.
    suite = {t.task_id: t.pattern for t in get_suite()}
    for r in report.results:
        pat = suite.get(r.task_id, "general")
        by_pattern.setdefault(pat, []).append(r)

    notes: list[str] = []
    for pattern, results in sorted(by_pattern.items()):
        all_passed = all(r.passed for r in results)
        if all_passed:
            event = await tm.record_success(pattern, {"source": "eval_suite"})
            verb = "✓ success"
        else:
            failed = [r.task_id for r in results if not r.passed]
            event = await tm.record_failure(
                pattern, f"eval failures: {failed}", {"source": "eval_suite"}
            )
            verb = f"✗ failure ({len(failed)} task(s))"

        level = tm.get_trust_level(pattern).value
        line = f"  pattern '{pattern}': {verb} -> trust={level}"
        if event is not None:
            line += f"   [LEVEL CHANGED: {event.old_level.value} -> {event.new_level.value}]"
        notes.append(line)

    return notes


def main() -> int:
    ap = argparse.ArgumentParser(description="Run GRIT eval suite")
    ap.add_argument("--no-trust", action="store_true",
                    help="run suite without updating the trust ladder")
    ap.add_argument("--json", action="store_true",
                    help="print machine-readable JSON instead of human report")
    ap.add_argument("--save", default="evals/last_report.json",
                    help="path to write JSON report")
    args = ap.parse_args()

    report = run_suite("grit-governance-v1", get_suite())
    path = save_report(report, args.save)

    trust_notes: list[str] = []
    if not args.no_trust:
        trust_notes = asyncio.run(_apply_to_trust(report))

    if args.json:
        out = report.to_dict()
        out["trust_notes"] = trust_notes
        out["report_path"] = path
        print(json.dumps(out, indent=2))
    else:
        print(report.human_readable())
        print(f"\nReport saved: {path}")
        if trust_notes:
            print("\nTRUST LADDER UPDATE:")
            print("\n".join(trust_notes))

    return 0 if report.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
