#!/usr/bin/env python3
"""
grit — standalone CLI for the cost-governance layer.

Zero heavy dependencies (no rich/pydantic/httpx). Pure stdlib + GRIT's own
planner/governor/evals. This is the command you'll actually reach for at the
keyboard. Run from the repo root.

    python grit.py govern "Research DeFi protocols and review findings"
    python grit.py govern "Port Flask to FastAPI" --trust UNTRUSTED
    python grit.py eval                 # run suite, update trust ladder
    python grit.py eval --no-trust      # run suite only
    python grit.py trust                # show current trust ladder state
"""

import argparse
import asyncio
import json
import sys


def cmd_govern(args) -> int:
    from src.workflow.cost_governor import govern_task, GovernorConfig
    decision = govern_task(args.task, GovernorConfig(trust_level=args.trust))
    chosen = decision.downgraded_plan or decision.plan
    print(chosen.human_readable())
    print(f"\nVERDICT: {decision.verdict.value.upper()}")
    for r in decision.reasons:
        print(f"  • {r}")
    print("\nROUTING SPEC (paste into Claude Code after your `ultracode:` prompt):")
    print(json.dumps(chosen.routing_spec(), indent=2))
    return 0


def cmd_eval(args) -> int:
    from src.evals.harness import run_suite, save_report
    from src.evals.suite import get_suite
    report = run_suite("grit-governance-v1", get_suite())
    path = save_report(report)
    print(report.human_readable())
    print(f"\nReport saved: {path}")
    if not args.no_trust:
        from src.evals.runner import _apply_to_trust
        notes = asyncio.run(_apply_to_trust(report))
        if notes:
            print("\nTRUST LADDER UPDATE:")
            print("\n".join(notes))
    return 0 if report.all_passed else 1


def cmd_trust(args) -> int:
    try:
        from src.governance.trust import get_trust_manager
    except Exception as e:
        print(f"trust module unavailable: {e}")
        return 1
    tm = get_trust_manager()
    histories = tm.get_all_histories()
    if not histories:
        print("No trust history yet. Run `python grit.py eval` first.")
        return 0
    print("TRUST LADDER STATE")
    print("=" * 50)
    for h in histories:
        print(f"  {h.pattern:14} {h.trust_level.value:11} "
              f"(✓{h.total_successes} ✗{h.total_failures}, "
              f"streak {h.consecutive_successes})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="grit", description="GRIT cost-governance CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("govern", help="plan + govern a task")
    g.add_argument("task", help="task description")
    g.add_argument("--trust", default="UNTRUSTED",
                   choices=["UNTRUSTED", "TRUSTED", "AUTONOMOUS"])
    g.set_defaults(func=cmd_govern)

    e = sub.add_parser("eval", help="run eval suite + update trust")
    e.add_argument("--no-trust", action="store_true")
    e.set_defaults(func=cmd_eval)

    t = sub.add_parser("trust", help="show trust ladder state")
    t.set_defaults(func=cmd_trust)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
