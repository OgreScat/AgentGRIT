"""Cells Interlinked context contract.

Twelve cells, selectively loaded; the value is the interlocks:
context constrains action; references constrain claims; scope constrains
delegation; quality constrains evidence; evidence gates checkpoint;
checkpoint constrains report; continuity is curated; next-state constrains
future action. Not a mega-prompt — a typed envelope the runtime validates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

ALWAYS_CELLS = ("task", "context", "quality", "scope", "evidence", "checkpoint", "report")
OVERLAYS: dict[str, tuple[str, ...]] = {
    "research": ("references",),
    "coding": ("references",),
    "design": ("references",),
    "legal": ("references",),
    "parallel": ("delegation",),
    "multi_session": ("continuity",),
    "workflow": ("next_state",),
}


class NextState(str, Enum):
    COMPLETED = "completed"
    NEEDS_REVISION = "needs_revision"
    BLOCKED = "blocked"
    AWAITING_HUMAN_APPROVAL = "awaiting_human_approval"
    ESCALATED = "escalated"
    ARCHIVED = "archived"


@dataclass
class CellsRun:
    """One task's populated envelope. Cells are dicts; absent = not loaded."""
    task: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    references: dict[str, Any] | None = None
    quality: dict[str, Any] = field(default_factory=dict)
    action: dict[str, Any] = field(default_factory=dict)
    scope: dict[str, Any] = field(default_factory=dict)
    delegation: list[dict[str, Any]] | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    continuity: dict[str, Any] | None = None
    checkpoint: dict[str, Any] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)
    next_state: str | None = None
    modes: tuple[str, ...] = ()


def required_cells(modes: tuple[str, ...]) -> set[str]:
    req = set(ALWAYS_CELLS)
    for m in modes:
        req.update(OVERLAYS.get(m, ()))
    return req


def validate_run(run: CellsRun) -> list[str]:
    """Interlock validator. Empty list = contract satisfied. Fail closed."""
    v: list[str] = []
    for cell in required_cells(run.modes):
        val = getattr(run, cell, None)
        if val is None or val == {} or val == []:
            v.append(f"required cell empty: {cell}")
    # evidence gates checkpoint; checkpoint constrains report/next-state
    cp = (run.checkpoint or {}).get("result", "")
    ns = run.next_state
    if ns is not None and ns not in {s.value for s in NextState}:
        v.append(f"next_state invalid: {ns}")
    if ns == NextState.COMPLETED.value:
        if not (run.evidence or {}).get("items"):
            v.append("completed without named evidence items")
        if cp != "pass":
            v.append("completed without a passing checkpoint")
    if cp and cp != "pass" and ns == NextState.COMPLETED.value:
        v.append("checkpoint result forbids completion")
    # scope constrains delegation
    for i, d in enumerate(run.delegation or []):
        for key in ("objective", "inputs", "allowed_tools", "output_schema", "budget"):
            if not d.get(key):
                v.append(f"delegation[{i}] missing {key}")
    # references constrain claims: unreferenced claims must carry labels
    for c in (run.report or {}).get("claims", []):
        if not c.get("reference") and c.get("label") not in ("ASSUMPTION", "UNKNOWN", "LIKELY", "CERTAIN"):
            v.append("claim without reference or label")
    return v
