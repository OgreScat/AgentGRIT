"""
Priority manager -- project weight lookup for budget pressure decisions.

Pure functions over config/priorities.yaml (via config_loader). When the file
is absent, every project gets default_weight=0.5 — identical to "no priority
system" behavior for budget scaling (scale factor 1.0 at weight 0.5).

Weights are 0.0..1.0:
  high (>= high_priority_threshold, default 0.75) → protected from soft-budget
  starvation under budget pressure (still subject to hard ceiling + escalate).
"""

from __future__ import annotations

import re
from typing import Any

from src.governance.config_loader import load_priorities_config


def weight_for(project: str | None, *, config: dict[str, Any] | None = None) -> float:
    """Return priority weight in [0.0, 1.0] for a project key."""
    cfg = config if config is not None else load_priorities_config()
    default = float(cfg.get("default_weight", 0.5))
    if not project:
        return max(0.0, min(1.0, default))
    projects = cfg.get("projects") or {}
    key = str(project).strip().lower()
    if key in projects:
        try:
            return max(0.0, min(1.0, float(projects[key])))
        except (TypeError, ValueError):
            return max(0.0, min(1.0, default))
    return max(0.0, min(1.0, default))


def high_priority_threshold(config: dict[str, Any] | None = None) -> float:
    cfg = config if config is not None else load_priorities_config()
    try:
        return float(cfg.get("high_priority_threshold", 0.75))
    except (TypeError, ValueError):
        return 0.75


def is_high_priority(project: str | None, *, config: dict[str, Any] | None = None) -> bool:
    """True when weight >= threshold — protects critical work from soft downgrade."""
    return weight_for(project, config=config) >= high_priority_threshold(config)


def detect_project_from_task(task: str) -> str | None:
    """Best-effort project key from task text.

    1. context_loader.detect_project if any PROJECT_PATHS registered
    2. keys listed in priorities.yaml projects map
    Conservative: false negative preferred over wrong project.
    """
    if not task:
        return None
    try:
        from src.governance.context_loader import detect_project
        hit = detect_project(task)
        if hit:
            return hit
    except Exception:
        pass
    cfg = load_priorities_config()
    projects = cfg.get("projects") or {}
    lower = task.lower()
    # Longer keys first so "my-api-service" wins over "api"
    for name in sorted(projects.keys(), key=len, reverse=True):
        if name and name in lower:
            return name
    # Optional explicit marker: project:foo or [project:foo]
    m = re.search(r"\[?project:([a-z0-9_-]+)\]?", lower)
    if m:
        return m.group(1)
    return None


def budget_scale(weight: float) -> float:
    """Map weight → multiplier on soft/escalate thresholds.

    weight 0.0 → 0.6 (earlier downgrade)
    weight 0.5 → 1.0 (neutral — default)
    weight 1.0 → 1.4 (more room before soft/escalate)
    Hard ceiling is never scaled by this function.
    """
    w = max(0.0, min(1.0, float(weight)))
    return 0.6 + 0.8 * w
