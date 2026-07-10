"""
Operator console rollup — READ-ONLY aggregation of existing JSONL logs.

No side effects, no POSTs, no action triggers. Missing logs → empty sections.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.utils.logging import DEFAULT_LOG_DIR, read_jsonl_tail, count_jsonl


def _ts(entry: dict) -> str:
    return str(entry.get("ts") or entry.get("timestamp") or "")


def _decisions(log_dir: Path, n: int = 40) -> list[dict[str, Any]]:
    rows = read_jsonl_tail("decisions.jsonl", n=n, log_dir=log_dir)
    out = []
    for r in reversed(rows):  # newest first for the stream
        out.append({
            "ts": _ts(r),
            "disposition": r.get("disposition") or "unknown",
            "action": (r.get("action") or "")[:160],
            "rationale": (r.get("rationale") or r.get("bylaw_reason") or "")[:200],
            "authorized_by": r.get("authorized_by") or "",
            "provider": r.get("chosen_provider"),
            "category": r.get("category"),
        })
    return out


def _escalations(log_dir: Path, n: int = 30) -> list[dict[str, Any]]:
    """Recent escalation log events. Prefer pending-looking entries."""
    rows = read_jsonl_tail("escalations.jsonl", n=n, log_dir=log_dir)
    out = []
    for r in reversed(rows):
        data = r.get("data") if isinstance(r.get("data"), dict) else {}
        event = r.get("event") or data.get("event") or "escalation"
        out.append({
            "ts": _ts(r),
            "event": event,
            "id": data.get("id") or r.get("id") or "",
            "requester": data.get("requester") or r.get("requester") or "",
            "category": data.get("category") or "",
            "risk_level": data.get("risk_level"),
            "requires_owner": data.get("requires_owner"),
            "expires_at": data.get("expires_at") or "",
            "status": data.get("status") or (
                "pending" if "created" in str(event) else str(event)
            ),
        })
    return out


def _router_by_provider(log_dir: Path, n: int = 200) -> dict[str, Any]:
    rows = read_jsonl_tail("router.jsonl", n=n, log_dir=log_dir)
    counts: Counter[str] = Counter()
    recent = []
    for r in rows:
        prov = str(r.get("provider") or "unknown")
        counts[prov] += 1
    for r in reversed(rows[-15:]):
        recent.append({
            "ts": _ts(r),
            "provider": r.get("provider"),
            "category": r.get("category"),
            "confidence": r.get("confidence"),
            "estimated_cost_usd": r.get("estimated_cost_usd"),
        })
    return {
        "by_provider": dict(counts.most_common()),
        "total": sum(counts.values()),
        "recent": recent,
    }


def _debrief_counts(log_dir: Path) -> dict[str, Any]:
    """Lightweight same-day counts (no full debrief render)."""
    today = date.today().isoformat()
    decisions = read_jsonl_tail("decisions.jsonl", n=500, log_dir=log_dir)
    disp: Counter[str] = Counter()
    today_n = 0
    for r in decisions:
        ts = _ts(r)
        if ts.startswith(today):
            today_n += 1
            disp[str(r.get("disposition") or "unknown")] += 1
    research = read_jsonl_tail("research_budget.jsonl", n=200, log_dir=log_dir)
    paid_today = sum(1 for r in research if str(r.get("date") or "").startswith(today))
    return {
        "day": today,
        "decision_count_today": today_n,
        "dispositions_today": dict(disp),
        "research_paid_today": paid_today,
        "decisions_total_file": count_jsonl("decisions.jsonl", log_dir=log_dir),
    }


def _trust_snapshot() -> dict[str, Any]:
    try:
        from src.governance.trust import get_trust_manager
        stats = get_trust_manager().get_statistics()
        return {
            "by_level": stats.get("by_level") or {},
            "success_rate": stats.get("success_rate"),
            "recent_promotions": stats.get("recent_promotions"),
            "recent_demotions": stats.get("recent_demotions"),
        }
    except Exception:
        return {
            "by_level": {},
            "success_rate": None,
            "recent_promotions": 0,
            "recent_demotions": 0,
        }


def _observe_summary(observe_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not observe_snapshot:
        return {
            "available": False,
            "ts": None,
            "feed": None,
            "actionable_count": 0,
            "non_actionable_count": 0,
            "verdict": None,
            "event_count": 0,
        }
    result = observe_snapshot.get("result") or {}
    events = result.get("events") or []
    return {
        "available": True,
        "ts": observe_snapshot.get("ts"),
        "feed": observe_snapshot.get("feed"),
        "actionable_count": result.get("actionable_count", 0),
        "non_actionable_count": result.get("non_actionable_count", 0),
        "verdict": result.get("assessment_verdict"),
        "event_count": len(events),
    }


def build_console_rollup(
    log_dir: Path | None = None,
    *,
    observe_snapshot: dict[str, Any] | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    """Assemble the JSON payload for GET /console/data. Never raises."""
    root = Path(log_dir) if log_dir is not None else DEFAULT_LOG_DIR
    try:
        decisions = _decisions(root, n=limit)
        escalations = _escalations(root, n=limit)
        router = _router_by_provider(root, n=max(limit * 4, 100))
        debrief = _debrief_counts(root)
        trust = _trust_snapshot()
        observe = _observe_summary(observe_snapshot)
        missing = []
        for name in ("decisions.jsonl", "escalations.jsonl", "router.jsonl"):
            if not (root / name).exists():
                missing.append(name)
        return {
            "ts": datetime.utcnow().isoformat() + "Z",
            "read_only": True,
            "log_dir": str(root),
            "missing_logs": missing,
            "decisions": decisions,
            "escalations": escalations,
            "router": router,
            "debrief": debrief,
            "trust": trust,
            "observe": observe,
        }
    except Exception as exc:  # noqa: BLE001 — fail-safe empty shell
        return {
            "ts": datetime.utcnow().isoformat() + "Z",
            "read_only": True,
            "log_dir": str(root),
            "missing_logs": ["*"],
            "error": str(exc)[:200],
            "decisions": [],
            "escalations": [],
            "router": {"by_provider": {}, "total": 0, "recent": []},
            "debrief": {"day": date.today().isoformat(), "decision_count_today": 0,
                        "dispositions_today": {}, "research_paid_today": 0,
                        "decisions_total_file": 0},
            "trust": {"by_level": {}},
            "observe": {"available": False},
        }
