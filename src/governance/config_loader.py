"""
Config loader -- file-backed defaults for budget + project priorities.

Loads YAML (or JSON) from config/ when present. When files are absent or
malformed, returns defaults IDENTICAL to GovernorConfig / env historical
values so behavior is backward-compatible.

No third-party YAML dependency: a minimal subset parser handles the simple
maps we ship. Full PyYAML is used if installed.

  config/budget.yaml      soft_budget, escalate_budget, hard_ceiling,
                          research_max_paid_per_day
  config/priorities.yaml  default_weight + projects: {name: weight}

Per-project research thresholds (optional):
  projects/<name>/research_thresholds.yaml
  config/projects/<name>.yaml
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

# Repo root = parents[2] from src/governance/
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_DIR = _REPO_ROOT / "config"

# Defaults mirror src/workflow/cost_governor.GovernorConfig + research env.
DEFAULT_BUDGET = {
    "soft_budget": 2.00,
    "escalate_budget": 5.00,
    "hard_ceiling": 25.00,
    "research_max_paid_per_day": 25,
}

DEFAULT_PRIORITIES = {
    "default_weight": 0.5,
    "high_priority_threshold": 0.75,
    "projects": {},
}

# Research quality defaults (match research_quality._thr defaults).
DEFAULT_RESEARCH_THRESHOLDS = {
    "strong": 0.82,
    "corroborated": 0.65,
    "adequate": 0.62,
    "contradiction_overlap": 0.18,
}


def config_dir() -> Path:
    override = os.environ.get("GRIT_CONFIG_DIR")
    if override:
        return Path(override)
    return _CONFIG_DIR


def repo_root() -> Path:
    return _REPO_ROOT


def _minimal_yaml(text: str) -> Any:
    """Parse a tiny YAML subset: nested maps, scalars, no lists-of-maps needed.

    Supports:
      key: value
      parent:
        child: 1.0
    Values: numbers, booleans, bare/quoted strings.
    """
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        # Expand tabs
        line = raw.replace("\t", "  ")
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()
        if ":" not in content:
            continue
        key, _, rest = content.partition(":")
        key = key.strip()
        rest = rest.strip()

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if rest == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _scalar(rest)
    return root


def _scalar(s: str) -> Any:
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    low = s.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none", "~"):
        return None
    try:
        if re.fullmatch(r"-?\d+", s):
            return int(s)
        if re.fullmatch(r"-?\d+\.\d+", s):
            return float(s)
    except ValueError:
        pass
    return s


def load_mapping(path: Path) -> dict[str, Any]:
    """Load a mapping from .yaml/.yml/.json. Empty dict on any failure."""
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        try:
            data = _minimal_yaml(text)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def load_budget_config() -> dict[str, float | int]:
    """Budget thresholds: file overrides, else env, else DEFAULT_BUDGET."""
    out = dict(DEFAULT_BUDGET)
    file_data = load_mapping(config_dir() / "budget.yaml")
    if not file_data:
        file_data = load_mapping(config_dir() / "budget.yml")
    for k in DEFAULT_BUDGET:
        if k in file_data and file_data[k] is not None:
            try:
                out[k] = type(DEFAULT_BUDGET[k])(file_data[k])
            except (TypeError, ValueError):
                pass
    # Env still wins (operator override) — same names as budget_governor historically.
    env_map = {
        "soft_budget": "GRIT_SOFT_BUDGET",
        "escalate_budget": "GRIT_ESCALATE_BUDGET",
        "hard_ceiling": "GRIT_HARD_CEILING",
        "research_max_paid_per_day": "RESEARCH_MAX_PAID_PER_DAY",
    }
    for key, env in env_map.items():
        raw = os.environ.get(env)
        if raw is not None and raw != "":
            try:
                out[key] = type(DEFAULT_BUDGET[key])(float(raw) if key != "research_max_paid_per_day" else int(float(raw)))
            except ValueError:
                pass
    return out


def load_priorities_config() -> dict[str, Any]:
    out: dict[str, Any] = {
        "default_weight": DEFAULT_PRIORITIES["default_weight"],
        "high_priority_threshold": DEFAULT_PRIORITIES["high_priority_threshold"],
        "projects": dict(DEFAULT_PRIORITIES["projects"]),
    }
    file_data = load_mapping(config_dir() / "priorities.yaml")
    if not file_data:
        file_data = load_mapping(config_dir() / "priorities.yml")
    if "default_weight" in file_data:
        try:
            out["default_weight"] = float(file_data["default_weight"])
        except (TypeError, ValueError):
            pass
    if "high_priority_threshold" in file_data:
        try:
            out["high_priority_threshold"] = float(file_data["high_priority_threshold"])
        except (TypeError, ValueError):
            pass
    projects = file_data.get("projects")
    if isinstance(projects, dict):
        cleaned = {}
        for name, w in projects.items():
            try:
                cleaned[str(name).lower()] = float(w)
            except (TypeError, ValueError):
                continue
        out["projects"] = cleaned
    return out


def load_project_research_thresholds(project: str | None) -> dict[str, float]:
    """Per-project research truth bars. Env-global defaults always baseline.

    Lookup order (later overrides earlier only for present keys):
      1. DEFAULT_RESEARCH_THRESHOLDS
      2. env GRIT_EVIDENCE_* (global)
      3. config/projects/<project>.yaml
      4. projects/<project>/research_thresholds.yaml
    """
    out = dict(DEFAULT_RESEARCH_THRESHOLDS)
    env_keys = {
        "strong": "GRIT_EVIDENCE_STRONG",
        "corroborated": "GRIT_EVIDENCE_CORROBORATED",
        "adequate": "GRIT_EVIDENCE_ADEQUATE",
        "contradiction_overlap": "GRIT_CONTRADICTION_OVERLAP",
    }
    for k, env in env_keys.items():
        raw = os.environ.get(env)
        if raw:
            try:
                out[k] = float(raw)
            except ValueError:
                pass
    if not project:
        return out
    slug = str(project).strip().lower()
    candidates = [
        config_dir() / "projects" / f"{slug}.yaml",
        config_dir() / "projects" / f"{slug}.yml",
        _REPO_ROOT / "projects" / slug / "research_thresholds.yaml",
        _REPO_ROOT / "projects" / slug / "research_thresholds.yml",
    ]
    for path in candidates:
        data = load_mapping(path)
        if not data:
            continue
        # Allow nested research: {...} or flat keys
        block = data.get("research_thresholds") if isinstance(data.get("research_thresholds"), dict) else data
        for k in DEFAULT_RESEARCH_THRESHOLDS:
            if k in block and block[k] is not None:
                try:
                    out[k] = float(block[k])
                except (TypeError, ValueError):
                    pass
        break  # first file found wins
    return out
