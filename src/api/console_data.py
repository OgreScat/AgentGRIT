"""
Operator console rollups — READ-ONLY multi-screen aggregation of JSONL logs.

Screens: overview | tasks | governance | research | models | audit
Plus legacy build_console_rollup() for back-compat (flat payload).

No side effects, no POSTs. Missing logs → empty sections, never raises.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.utils.logging import DEFAULT_LOG_DIR, read_jsonl_tail, count_jsonl

SCREENS = ("overview", "tasks", "governance", "research", "models", "audit", "flat")

_LOCAL_PROVIDERS = frozenset({"ollama", "local", "bylaws", "autonomy", "observe"})


def _ts(entry: dict) -> str:
    return str(entry.get("ts") or entry.get("timestamp") or "")


def _missing(log_dir: Path, names: tuple[str, ...]) -> list[str]:
    return [n for n in names if not (log_dir / n).exists()]


def _decisions_raw(log_dir: Path, n: int = 80) -> list[dict[str, Any]]:
    return list(reversed(read_jsonl_tail("decisions.jsonl", n=n, log_dir=log_dir)))


def _decision_row(r: dict[str, Any]) -> dict[str, Any]:
    evidence = r.get("evidence") if isinstance(r.get("evidence"), dict) else {}
    return {
        "ts": _ts(r),
        "disposition": r.get("disposition") or "unknown",
        "action": (r.get("action") or "")[:200],
        "project": r.get("project"),
        "rationale": (r.get("rationale") or r.get("bylaw_reason") or "")[:240],
        "authorized_by": r.get("authorized_by") or "",
        "provider": r.get("chosen_provider"),
        "category": r.get("category"),
        "confidence": r.get("confidence"),
        "estimated_cost_usd": r.get("estimated_cost_usd"),
        "route_reason": (r.get("route_reason") or "")[:200],
        "bylaw_action": r.get("bylaw_action"),
        "bylaw_reason": (r.get("bylaw_reason") or "")[:200],
        "evidence_verdict": evidence.get("verdict"),
        "evidence_score": evidence.get("score"),
        "evidence_require_human": evidence.get("require_human"),
        "alternatives": r.get("alternatives_considered") or [],
        "id": f"{_ts(r)}|{ (r.get('action') or '')[:40]}",
    }


def _decisions(log_dir: Path, n: int = 40) -> list[dict[str, Any]]:
    return [_decision_row(r) for r in _decisions_raw(log_dir, n)]


def _escalations(log_dir: Path, n: int = 40) -> list[dict[str, Any]]:
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


def _router_rows(log_dir: Path, n: int = 200) -> list[dict[str, Any]]:
    rows = read_jsonl_tail("router.jsonl", n=n, log_dir=log_dir)
    out = []
    for r in rows:
        out.append({
            "ts": _ts(r),
            "provider": r.get("provider"),
            "category": r.get("category"),
            "confidence": r.get("confidence"),
            "reason": (r.get("reason") or "")[:220],
            "capabilities": r.get("capabilities") or [],
            "estimated_cost_usd": r.get("estimated_cost_usd"),
            "task_preview": (r.get("task_preview") or "")[:120],
        })
    return out


def _router_by_provider(log_dir: Path, n: int = 200) -> dict[str, Any]:
    rows = _router_rows(log_dir, n)
    counts: Counter[str] = Counter()
    cost_sum = 0.0
    local_n = cloud_n = 0
    for r in rows:
        prov = str(r.get("provider") or "unknown")
        counts[prov] += 1
        try:
            cost_sum += float(r.get("estimated_cost_usd") or 0)
        except (TypeError, ValueError):
            pass
        if prov.lower() in _LOCAL_PROVIDERS:
            local_n += 1
        else:
            cloud_n += 1
    recent = list(reversed(rows[-20:]))
    return {
        "by_provider": dict(counts.most_common()),
        "total": sum(counts.values()),
        "recent": recent,
        "estimated_cost_sum": round(cost_sum, 6),
        "local_count": local_n,
        "cloud_count": cloud_n,
    }


def _bylaws(log_dir: Path, n: int = 40) -> list[dict[str, Any]]:
    rows = read_jsonl_tail("bylaws.jsonl", n=n, log_dir=log_dir)
    out = []
    for r in reversed(rows):
        out.append({
            "ts": _ts(r),
            "action": r.get("action") or "",
            "command": (r.get("command") or "")[:160],
            "reason": (r.get("reason") or "")[:200],
            "rule": r.get("rule") or "",
            "role": r.get("role") or "",
        })
    return out


def _notifications(log_dir: Path, n: int = 30) -> list[dict[str, Any]]:
    rows = read_jsonl_tail("notifications.jsonl", n=n, log_dir=log_dir)
    out = []
    for r in reversed(rows):
        out.append({
            "ts": _ts(r),
            "channel": r.get("channel") or "",
            "ok": r.get("ok"),
            "text": (r.get("text") or "")[:160],
            "detail": (r.get("detail") or "")[:120],
        })
    return out


def _briefs(log_dir: Path, n: int = 20) -> list[dict[str, Any]]:
    rows = read_jsonl_tail("briefs.jsonl", n=n, log_dir=log_dir)
    out = []
    for r in reversed(rows):
        out.append({
            "ts": _ts(r),
            "id": r.get("id") or r.get("run_id") or "",
            "kind": r.get("kind") or "",
            "question": (r.get("question") or "")[:120],
            "disposition": r.get("disposition") or "",
            "confidence_band": r.get("confidence_band") or "",
            "confidence_score": r.get("confidence_score"),
            "evidence_verdict": r.get("evidence_verdict"),
            "contested": bool(r.get("contested")),
            "dropped_count": r.get("dropped_count") or 0,
            "authorities_n": len(r.get("authorities") or []),
            "autonomy_gate": r.get("autonomy_gate"),
            "provider": r.get("provider"),
        })
    return out


def _debrief_counts(log_dir: Path) -> dict[str, Any]:
    today = date.today().isoformat()
    decisions = read_jsonl_tail("decisions.jsonl", n=500, log_dir=log_dir)
    disp: Counter[str] = Counter()
    today_n = 0
    last_blocked = None
    for r in decisions:
        ts = _ts(r)
        disp_v = str(r.get("disposition") or "unknown")
        if ts.startswith(today):
            today_n += 1
            disp[disp_v] += 1
        if disp_v in ("refused",) or r.get("bylaw_action") == "block":
            last_blocked = {
                "ts": ts,
                "action": (r.get("action") or "")[:120],
                "reason": (r.get("rationale") or r.get("bylaw_reason") or "")[:160],
            }
    # last blocked should be newest — scan reversed
    for r in reversed(decisions):
        if r.get("disposition") == "refused" or r.get("bylaw_action") == "block":
            last_blocked = {
                "ts": _ts(r),
                "action": (r.get("action") or "")[:120],
                "reason": (r.get("rationale") or r.get("bylaw_reason") or "")[:160],
            }
            break
    research = read_jsonl_tail("research_budget.jsonl", n=200, log_dir=log_dir)
    paid_today = sum(1 for r in research if str(r.get("date") or "").startswith(today))
    return {
        "day": today,
        "decision_count_today": today_n,
        "dispositions_today": dict(disp),
        "research_paid_today": paid_today,
        "decisions_total_file": count_jsonl("decisions.jsonl", log_dir=log_dir),
        "last_blocked": last_blocked,
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
            "events_sample": [],
        }
    result = observe_snapshot.get("result") or {}
    events = result.get("events") or []
    sample = []
    for e in events[:8]:
        if not isinstance(e, dict):
            continue
        sample.append({
            "title": (e.get("title") or "")[:100],
            "actionable": e.get("actionable"),
            "freshness_grade": e.get("freshness_grade"),
            "evidence_grade": e.get("evidence_grade"),
            "source_id": e.get("source_id"),
        })
    return {
        "available": True,
        "ts": observe_snapshot.get("ts"),
        "feed": observe_snapshot.get("feed"),
        "actionable_count": result.get("actionable_count", 0),
        "non_actionable_count": result.get("non_actionable_count", 0),
        "verdict": result.get("assessment_verdict"),
        "event_count": len(events),
        "events_sample": sample,
    }


def _pending_escalation_count(escalations: list[dict]) -> int:
    return sum(
        1 for e in escalations
        if str(e.get("status") or "").lower() in ("pending",) or "created" in str(e.get("event") or "")
    )


def _budget_thresholds() -> dict[str, Any]:
    try:
        from src.governance.config_loader import load_budget_config
        return load_budget_config()
    except Exception:
        return {
            "soft_budget": 2.0,
            "escalate_budget": 5.0,
            "hard_ceiling": 25.0,
            "research_max_paid_per_day": 25,
        }


def _pillars_note(log_dir: Path) -> dict[str, Any]:
    """Pillar scores are computed in-process; no dedicated pillars.jsonl today."""
    path = log_dir / "pillars.jsonl"
    if path.exists():
        rows = read_jsonl_tail("pillars.jsonl", n=20, log_dir=log_dir)
        return {"available": True, "entries": list(reversed(rows)), "note": None}
    return {
        "available": False,
        "entries": [],
        "note": (
            "No pillars.jsonl yet — Pillar Inspector runs in-process on proposals "
            "but does not append a dedicated console log. Screen is intentionally thin."
        ),
    }


def _projects_stub(log_dir: Path) -> dict[str, Any]:
    """Honest stub: only surface project keys if decisions carry them."""
    rows = read_jsonl_tail("decisions.jsonl", n=200, log_dir=log_dir)
    counts: Counter[str] = Counter()
    for r in rows:
        p = r.get("project")
        if p:
            counts[str(p)] += 1
    if not counts:
        return {
            "available": False,
            "projects": {},
            "note": "No per-project fields in decisions.jsonl — projects pane not fabricated.",
        }
    return {"available": True, "projects": dict(counts.most_common()), "note": None}


# ── Screen rollups ────────────────────────────────────────────────────────────

def screen_overview(
    log_dir: Path,
    *,
    observe_snapshot: dict[str, Any] | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    decisions = _decisions(log_dir, n=limit)
    escalations = _escalations(log_dir, n=limit)
    router = _router_by_provider(log_dir, n=max(limit * 4, 100))
    debrief = _debrief_counts(log_dir)
    trust = _trust_snapshot()
    observe = _observe_summary(observe_snapshot)
    # Active agents: not a dedicated log — best-effort from authorized_by prefixes
    agents: Counter[str] = Counter()
    for d in decisions:
        ab = str(d.get("authorized_by") or "")
        if ab.startswith("agent:"):
            agents[ab.split(":", 1)[1].split(":")[0]] += 1
        elif ab.startswith("router:"):
            agents["router"] += 1
        elif ab.startswith("observe:"):
            agents["observe"] += 1
    timeline = []
    for d in decisions[:15]:
        timeline.append({
            "ts": d["ts"], "kind": "decision", "label": d["disposition"],
            "text": d["action"][:100],
        })
    for e in escalations[:8]:
        timeline.append({
            "ts": e["ts"], "kind": "escalation", "label": e.get("status") or e.get("event"),
            "text": f"{e.get('id')} {e.get('category')}",
        })
    timeline.sort(key=lambda x: x.get("ts") or "", reverse=True)
    return {
        "screen": "overview",
        "kpis": {
            "decisions_today": debrief.get("decision_count_today", 0),
            "dispositions_today": debrief.get("dispositions_today") or {},
            "pending_escalations": _pending_escalation_count(escalations),
            "trust_promotions": trust.get("recent_promotions"),
            "trust_demotions": trust.get("recent_demotions"),
            "router_total": router.get("total", 0),
            "router_cost_sum": router.get("estimated_cost_sum", 0),
            "last_blocked": debrief.get("last_blocked"),
            "active_agent_hints": dict(agents.most_common(8)),
            "observe_available": observe.get("available"),
        },
        "timeline": timeline[:25],
        "trust": trust,
        "observe": observe,
        "debrief": debrief,
    }


def screen_tasks(log_dir: Path, *, limit: int = 60) -> dict[str, Any]:
    decisions = _decisions(log_dir, n=limit)
    router = _router_rows(log_dir, n=limit)
    return {
        "screen": "tasks",
        "tasks": decisions,
        "router_recent": list(reversed(router[-30:])),
        "filters": {
            "dispositions": sorted({d["disposition"] for d in decisions}),
            "providers": sorted({str(d.get("provider") or "") for d in decisions if d.get("provider")}),
        },
    }


def screen_governance(log_dir: Path, *, limit: int = 40) -> dict[str, Any]:
    return {
        "screen": "governance",
        "bylaws": _bylaws(log_dir, n=limit),
        "escalations": _escalations(log_dir, n=limit),
        "decisions": _decisions(log_dir, n=limit),
        "pillars": _pillars_note(log_dir),
        "note": (
            "Approvals are NOT available here — console is read-only. "
            "Use CLI / hardened Telegram for owner decisions."
        ),
    }


def screen_research(
    log_dir: Path,
    *,
    observe_snapshot: dict[str, Any] | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    briefs = _briefs(log_dir, n=limit)
    contested = [b for b in briefs if b.get("contested")]
    weak = [
        b for b in briefs
        if (b.get("confidence_band") in ("thin", "flagged"))
        or (b.get("evidence_verdict") in ("weak", "insufficient", "contested"))
    ]
    observe = _observe_summary(observe_snapshot)
    # Decision rows with evidence verdicts
    evidence_rows = []
    for d in _decisions(log_dir, n=limit):
        if d.get("evidence_verdict"):
            evidence_rows.append({
                "ts": d["ts"],
                "action": d["action"][:100],
                "verdict": d["evidence_verdict"],
                "score": d.get("evidence_score"),
                "require_human": d.get("evidence_require_human"),
            })
    return {
        "screen": "research",
        "briefs": briefs,
        "contested_briefs": contested,
        "weak_or_flagged": weak,
        "decision_evidence": evidence_rows,
        "observe": observe,
        "research_budget_today": _debrief_counts(log_dir).get("research_paid_today", 0),
    }


def screen_models(log_dir: Path, *, limit: int = 100) -> dict[str, Any]:
    router = _router_by_provider(log_dir, n=max(limit, 100))
    thr = _budget_thresholds()
    why = []
    for r in router.get("recent") or []:
        why.append({
            "ts": r.get("ts"),
            "provider": r.get("provider"),
            "category": r.get("category"),
            "reason": r.get("reason"),
            "confidence": r.get("confidence"),
            "task_preview": r.get("task_preview"),
            "estimated_cost_usd": r.get("estimated_cost_usd"),
            "capabilities": r.get("capabilities"),
        })
    return {
        "screen": "models",
        "by_provider": router.get("by_provider") or {},
        "total": router.get("total", 0),
        "local_count": router.get("local_count", 0),
        "cloud_count": router.get("cloud_count", 0),
        "estimated_cost_sum": router.get("estimated_cost_sum", 0),
        "budget_thresholds": thr,
        "why_this_model": why,
    }


def screen_audit(log_dir: Path, *, limit: int = 40) -> dict[str, Any]:
    return {
        "screen": "audit",
        "decisions": _decisions(log_dir, n=limit),
        "briefs": _briefs(log_dir, n=limit),
        "notifications": _notifications(log_dir, n=limit),
        "redaction_note": (
            "Outputs that pass through decision_record / brief_record / notify "
            "use src.security.redact where configured; console only displays stored text."
        ),
        "projects": _projects_stub(log_dir),
    }


def build_screen_rollup(
    screen: str = "overview",
    log_dir: Path | None = None,
    *,
    observe_snapshot: dict[str, Any] | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    """Per-screen rollup for GET /console/data?screen=… Fail-safe wrapper."""
    root = Path(log_dir) if log_dir is not None else DEFAULT_LOG_DIR
    screen = (screen or "overview").strip().lower()
    if screen == "flat":
        return build_console_rollup(root, observe_snapshot=observe_snapshot, limit=limit)
    try:
        builders = {
            "overview": lambda: screen_overview(root, observe_snapshot=observe_snapshot, limit=limit),
            "tasks": lambda: screen_tasks(root, limit=limit),
            "governance": lambda: screen_governance(root, limit=limit),
            "research": lambda: screen_research(root, observe_snapshot=observe_snapshot, limit=limit),
            "models": lambda: screen_models(root, limit=limit),
            "audit": lambda: screen_audit(root, limit=limit),
        }
        body = builders.get(screen, builders["overview"])()
        missing = _missing(root, (
            "decisions.jsonl", "escalations.jsonl", "router.jsonl",
            "bylaws.jsonl", "briefs.jsonl", "notifications.jsonl",
        ))
        return {
            "ts": datetime.utcnow().isoformat() + "Z",
            "read_only": True,
            "log_dir": str(root),
            "missing_logs": missing,
            "screens": list(SCREENS[:-1]),  # exclude flat from nav
            **body,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ts": datetime.utcnow().isoformat() + "Z",
            "read_only": True,
            "screen": screen,
            "error": str(exc)[:200],
            "missing_logs": ["*"],
            "screens": list(SCREENS[:-1]),
        }


def build_console_rollup(
    log_dir: Path | None = None,
    *,
    observe_snapshot: dict[str, Any] | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    """Legacy flat rollup (back-compat for existing clients/tests)."""
    root = Path(log_dir) if log_dir is not None else DEFAULT_LOG_DIR
    try:
        decisions = _decisions(root, n=limit)
        escalations = _escalations(root, n=limit)
        router = _router_by_provider(root, n=max(limit * 4, 100))
        debrief = _debrief_counts(root)
        trust = _trust_snapshot()
        observe = _observe_summary(observe_snapshot)
        missing = _missing(root, ("decisions.jsonl", "escalations.jsonl", "router.jsonl"))
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
    except Exception as exc:  # noqa: BLE001
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
