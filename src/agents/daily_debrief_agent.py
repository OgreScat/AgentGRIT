"""
Daily Debrief -- deterministic end-of-day rollup from existing audit logs.

Reads only what the runtime already writes:

  logs/decisions.jsonl       -- decision_record.record() (v0.1.3)
  logs/research_budget.jsonl -- paid research calls (research.py)
  logs/escalations.jsonl     -- escalation trail (if present)
  logs/notifications.jsonl   -- outbound notify trail
  logs/router.jsonl          -- routing evidence (optional summary)

No LLM, no invented spend. Counts and samples are derived from file lines.
Missing logs yield empty sections (fail-open for the debrief itself; the
absence is reported).

Usage:
    from src.agents.daily_debrief_agent import build_debrief, render
    print(render(build_debrief()))                 # today
    print(render(build_debrief(day="2026-07-09"))) # explicit day

CLI:
    python -m src.agents.daily_debrief_agent
    python -m src.agents.daily_debrief_agent 2026-07-09
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any


_DEFAULT_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"


def _day_str(day: str | None) -> str:
    return day or date.today().isoformat()


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except Exception:
        return []
    return out


def _entry_day(entry: dict) -> str | None:
    """Best-effort day extraction from common timestamp fields."""
    for key in ("date", "ts", "timestamp"):
        v = entry.get(key)
        if not v:
            continue
        s = str(v)
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            return s[:10]
    return None


def _for_day(entries: list[dict], day: str) -> list[dict]:
    matched = []
    for e in entries:
        d = _entry_day(e)
        # Undated lines are skipped: without a date we cannot attribute them to
        # `day`, and including them would inflate counts. Records written by
        # decision_record always carry `ts`, so this only drops entries from
        # loggers that omit a timestamp.
        if d == day:
            matched.append(e)
    return matched


@dataclass
class Debrief:
    day: str
    dispositions: dict[str, int] = field(default_factory=dict)
    decision_count: int = 0
    contested: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    escalated: list[str] = field(default_factory=list)
    research_paid: int = 0
    research_providers: dict[str, int] = field(default_factory=dict)
    notification_count: int = 0
    escalation_log_count: int = 0
    router_count: int = 0
    providers_routed: dict[str, int] = field(default_factory=dict)
    missing_logs: list[str] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)

    def to_entry(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "decision_count": self.decision_count,
            "dispositions": dict(self.dispositions),
            "contested_actions": list(self.contested),
            "refused_actions": list(self.refused),
            "escalated_actions": list(self.escalated),
            "research_paid": self.research_paid,
            "research_providers": dict(self.research_providers),
            "notification_count": self.notification_count,
            "escalation_log_count": self.escalation_log_count,
            "router_count": self.router_count,
            "providers_routed": dict(self.providers_routed),
            "missing_logs": list(self.missing_logs),
        }


def build_debrief(
    day: str | None = None,
    log_dir: Path | None = None,
) -> Debrief:
    """Aggregate today's (or `day`'s) audit logs into a Debrief."""
    d = _day_str(day)
    root = log_dir or _DEFAULT_LOG_DIR
    deb = Debrief(day=d)

    decisions_path = root / "decisions.jsonl"
    budget_path = root / "research_budget.jsonl"
    esc_path = root / "escalations.jsonl"
    notes_path = root / "notifications.jsonl"
    router_path = root / "router.jsonl"

    if not decisions_path.exists():
        deb.missing_logs.append("decisions.jsonl")
    if not budget_path.exists():
        deb.missing_logs.append("research_budget.jsonl")

    decisions = _for_day(_read_jsonl(decisions_path), d)
    deb.decision_count = len(decisions)
    disp = Counter(e.get("disposition") or "unknown" for e in decisions)
    deb.dispositions = dict(disp)

    for e in decisions:
        action = str(e.get("action") or "")[:80]
        disp_v = e.get("disposition")
        if disp_v == "contested" and action:
            deb.contested.append(action)
        elif disp_v == "refused" and action:
            deb.refused.append(action)
        elif disp_v == "escalated" and action:
            deb.escalated.append(action)

    # Cap samples for render readability
    deb.contested = deb.contested[:10]
    deb.refused = deb.refused[:10]
    deb.escalated = deb.escalated[:10]

    paid = _for_day(_read_jsonl(budget_path), d)
    deb.research_paid = len(paid)
    deb.research_providers = dict(
        Counter(str(e.get("provider") or "unknown") for e in paid)
    )

    notes = _for_day(_read_jsonl(notes_path), d)
    deb.notification_count = len(notes)

    esc = _for_day(_read_jsonl(esc_path), d)
    deb.escalation_log_count = len(esc)

    routes = _for_day(_read_jsonl(router_path), d)
    deb.router_count = len(routes)
    deb.providers_routed = dict(
        Counter(str(e.get("provider") or "unknown") for e in routes)
    )

    return deb


def render(deb: Debrief) -> str:
    """Plain-text debrief a human can read without the code."""
    lines = [
        f"DAILY DEBRIEF  ·  {deb.day}",
        "=" * 48,
        f"  decisions recorded: {deb.decision_count}",
    ]
    if deb.dispositions:
        parts = ", ".join(f"{k}={v}" for k, v in sorted(deb.dispositions.items()))
        lines.append(f"  dispositions:       {parts}")
    if deb.contested:
        lines.append(f"  contested ({len(deb.contested)}):")
        for a in deb.contested:
            lines.append(f"    ⚠ {a}")
    if deb.refused:
        lines.append(f"  refused ({len(deb.refused)}):")
        for a in deb.refused:
            lines.append(f"    ✗ {a}")
    if deb.escalated:
        lines.append(f"  escalated ({len(deb.escalated)}):")
        for a in deb.escalated:
            lines.append(f"    ⤴ {a}")

    lines.append(f"  paid research calls: {deb.research_paid}")
    if deb.research_providers:
        parts = ", ".join(f"{k}={v}" for k, v in sorted(deb.research_providers.items()))
        lines.append(f"    by provider: {parts}")

    lines.append(f"  notifications:       {deb.notification_count}")
    lines.append(f"  escalation log rows: {deb.escalation_log_count}")
    lines.append(f"  router decisions:    {deb.router_count}")
    if deb.providers_routed:
        parts = ", ".join(f"{k}={v}" for k, v in sorted(deb.providers_routed.items()))
        lines.append(f"    by provider: {parts}")

    if deb.missing_logs:
        lines.append(f"  missing logs: {', '.join(deb.missing_logs)}")

    # Foresight cue: if contested or refused exist, surface as attention items
    attention = []
    if deb.contested:
        attention.append(f"{len(deb.contested)} contested decision(s) need resolution")
    if deb.escalated:
        attention.append(f"{len(deb.escalated)} escalated action(s) still in the trail")
    if attention:
        lines.append("")
        lines.append("  ATTENTION:")
        for a in attention:
            lines.append(f"    • {a}")
    else:
        lines.append("")
        lines.append("  ATTENTION: none derived from today's records")

    lines.append("=" * 48)
    return "\n".join(lines)


def run_debrief(day: str | None = None, log_dir: Path | None = None) -> str:
    """Build + render. Convenience for CLI and agents."""
    return render(build_debrief(day=day, log_dir=log_dir))


def run_debrief_and_notify(
    day: str | None = None,
    log_dir: Path | None = None,
    *,
    notify: bool = False,
) -> str:
    """Build + render, optionally deliver via src.utils.notify.

    Schedulable entry point for cron / launchd / make debrief. The public
    repo does not install a GM supervisor — wire this command from your
    private scheduler if you want it nightly.

    notify=True (or env DEBRIEF_NOTIFY=1) calls notify(); channel is
    operator-configured (NOTIFY_CHANNEL). Failures never raise.
    """
    import os
    text = run_debrief(day=day, log_dir=log_dir)
    should = notify or os.environ.get("DEBRIEF_NOTIFY", "").strip() in ("1", "true", "yes")
    if should:
        try:
            from src.utils.notify import notify as _notify
            _notify(text[:3500])  # keep payloads bounded for SMS/Telegram
        except Exception:
            pass
    return text


if __name__ == "__main__":
    import sys
    args = [a for a in sys.argv[1:] if a != "--notify"]
    do_notify = "--notify" in sys.argv[1:]
    day_arg = args[0] if args else None
    print(run_debrief_and_notify(day=day_arg, notify=do_notify))
