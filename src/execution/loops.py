"""Governed loops -- "my job is to write loops," with a governance contract.

A loop is a recurring job you DECLARE (not a prompt you retype): a cadence + a task +
the authority it is allowed to act under. GRIT already runs loops -- the GM supervisor,
the nightly gardener -- but this makes "a loop" a first-class, user-authored primitive,
so new recurring work is a few lines of config instead of a bespoke launchd plist.

The governance twist -- the thing that separates this from an ungoverned cron: every
loop carries a TRUST CEILING. It may act autonomously only up to that risk level;
anything above it escalates to a human, exactly like the GM's autonomy threshold. A
loop cannot quietly grant itself more authority than you declared. That is the whole
difference between "agents looping unsupervised" and loops you can leave running.

Declared in loops.json at the repo root:
  [{"name": "gardener", "at": "03:00", "trust_ceiling": "medium", "cost": "free",
    "task": "run the memory-layer checkers"},
   {"name": "weekly-synthesis", "at": "07:00", "trust_ceiling": "low", "cost": "local",
    "task": "read the week's captures, write weekly-synthesis/<year>-W<week>.md"}]
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from pathlib import Path


class Trust(IntEnum):
    LOW = 10
    MEDIUM = 20
    HIGH = 30
    CRITICAL = 40

    @property
    def label(self) -> str:
        return self.name.lower()


_TRUST = {"low": Trust.LOW, "medium": Trust.MEDIUM,
          "high": Trust.HIGH, "critical": Trust.CRITICAL}


@dataclass
class Loop:
    name: str
    task: str = ""
    trust_ceiling: Trust = Trust.LOW
    cost: str = "free"           # free | local | paid
    at: str | None = None        # "HH:MM" daily
    every_seconds: int | None = None
    enabled: bool = True
    last_run: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "Loop":
        return cls(
            name=d["name"], task=d.get("task", ""),
            trust_ceiling=_TRUST.get(str(d.get("trust_ceiling", "low")).lower(), Trust.LOW),
            cost=d.get("cost", "free"),
            at=d.get("at"), every_seconds=d.get("every_seconds"),
            enabled=d.get("enabled", True), last_run=d.get("last_run"),
        )


def is_due(loop: Loop, now: datetime, last: datetime | None = None) -> bool:
    """Is this loop due at `now`? Deterministic; no side effects."""
    if not loop.enabled:
        return False
    if last is None and loop.last_run:
        try:
            last = datetime.fromisoformat(loop.last_run)
        except ValueError:
            last = None

    if loop.every_seconds:
        if last is None:
            return True
        return (now - last).total_seconds() >= loop.every_seconds

    if loop.at:
        hh, mm = (int(x) for x in loop.at.split(":"))
        if now.hour == hh and now.minute == mm:
            if last and last.replace(second=0, microsecond=0) == \
                    now.replace(second=0, microsecond=0):
                return False  # already ran this minute
            return True
        # catch-up: time passed today and we have not run today
        if (last is None or last.date() < now.date()) and (now.hour, now.minute) >= (hh, mm):
            return True
        return False

    return False


def can_autorun(loop: Loop, action_risk: Trust) -> bool:
    """A loop may act autonomously only up to its declared trust ceiling. An action
    above the ceiling returns False -> the caller must escalate to a human."""
    return action_risk <= loop.trust_ceiling


def load(path: Path) -> list[Loop]:
    """Load declared loops from a json file. Never raises; bad config -> no loops."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return [Loop.from_dict(d) for d in data]
    except Exception:  # noqa: BLE001
        return []


def due_loops(loops: list[Loop], now: datetime | None = None) -> list[Loop]:
    now = now or datetime.now()
    return [lp for lp in loops if is_due(lp, now)]
