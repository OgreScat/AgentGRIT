"""In-house competition mode -- the Agent-Arena pattern, brought on-device.

Run the same task through two or more *local* model configs, score each output, and
record the winner. Use it to answer 'which local model is actually better at this
kind of task' with data instead of vibes -- feeding the trust ladder and eval history.

Governance:
  - OPT-IN. Off unless COMPETITION_MODE=true (or explicitly invoked per call).
  - NEVER on safety-critical work. `compete(..., safety_critical=True)` refuses:
    safety and minors-policy decisions do not get gamified; they go to the human path.
  - Local only. Contestants are Ollama personas; no paid providers are entered into
    a competition (cost governance is not something to gamble with).
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable

from src.governance.deliberation import _ollama  # reuse the proven local caller

_LOG = Path(__file__).resolve().parents[2] / "logs" / "competition.jsonl"


class SafetyCriticalRefused(Exception):
    """Raised when competition mode is asked to run a safety-critical task."""


def mode_enabled() -> bool:
    return os.environ.get("COMPETITION_MODE", "false").lower() in ("1", "true", "yes")


def default_score(output: str) -> float:
    """A deterministic, transparent baseline score in [0, 1].

    Rewards a substantive, lexically varied answer; penalizes empty / one-word and
    runaway output. Intentionally simple and legible -- pass `score_fn` for a real
    domain scorer when running an actual evaluation.
    """
    if not output:
        return 0.0
    words = output.split()
    n = len(words)
    if n < 3:
        return 0.05
    if n <= 160:
        length_score = min(n / 160.0, 1.0)
    else:
        length_score = max(0.4, 1.0 - (n - 160) / 800.0)
    distinct = len(set(w.lower() for w in words)) / n  # lexical variety
    return round(0.7 * length_score + 0.3 * distinct, 4)


def compete(task: str, models: list[str], *,
            score_fn: Callable[[str], float] | None = None,
            safety_critical: bool = False, log_path: Path | None = None) -> dict:
    """Run `task` through each local model in `models`, score, and rank the results.

    Refuses safety-critical work. Fails safe: a model that does not respond scores 0.
    """
    if safety_critical:
        raise SafetyCriticalRefused(
            "competition mode is disabled for safety-critical tasks; use the human path")
    if len(models) < 2:
        raise ValueError("competition needs at least two contestants")
    scorer = score_fn or default_score
    entries = []
    for m in models:
        out = _ollama(m, task) or ""
        entries.append({"model": m, "score": scorer(out), "chars": len(out),
                        "output": out[:500]})
    entries.sort(key=lambda e: e["score"], reverse=True)
    result = {
        "ts": datetime.now().isoformat(),
        "task": task[:200],
        "winner": entries[0]["model"],
        "ranking": [{"model": e["model"], "score": e["score"]} for e in entries],
        "entries": entries,
    }
    try:
        p = log_path or _LOG
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.write(json.dumps(
                {k: result[k] for k in ("ts", "task", "winner", "ranking")}) + "\n")
    except Exception:  # noqa: BLE001
        pass
    return result
