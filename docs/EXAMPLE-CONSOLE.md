# Example: Operator Console (read-only)

Local web dashboard that **renders JSONL the runtime already writes**. It never
triggers agents, approvals, or observes-with-side-effects beyond reading logs
and an in-memory observe snapshot.

| Route | Method | Role |
|---|---|---|
| `/console` | GET | Self-contained HTML (inline CSS/JS, no CDN) |
| `/console/data` | GET | JSON rollup from `logs/*.jsonl` |

Auth: same fail-closed `X-API-Key` / loopback posture as the rest of the API.

## Run

```bash
# terminal 1 — API (loopback)
python -m src.main --api-only

# terminal 2
make console
# Open:  http://127.0.0.1:8000/console
# Data:  http://127.0.0.1:8000/console/data
```

## Screenshot-in-text (real `/console/data` rollup)

Captured from this tree’s `logs/` (shape only; counts move as you run tests):

```
┌─ AgentGRIT Console · READ-ONLY · no actions ──────── live · HH:MM:SSZ ─┐
│                                                                          │
│  TODAY · debrief counts                                                  │
│  [day: 2026-07-10] [decisions today: 49] [file total: 49]                │
│  [research paid: 0] [proceed: 35] [escalated: 10] [refused: 4]           │
│                                                                          │
│  DECISION STREAM                         ESCALATIONS QUEUE               │
│  ┌────────────────────────────┐          ┌────────────────────────────┐  │
│  │ REFUSED  · bylaws          │          │ pending · esc1             │  │
│  │ rm -rf /                   │          │ requester=test · risk=30   │  │
│  │ Law 0                      │          │                            │  │
│  │ ESCALATED · repo_steward   │          │ manager_decision · …       │  │
│  │ deploy to production       │          └────────────────────────────┘  │
│  │ PROCEED · router:allow     │                                          │
│  │ format helpers             │          ROUTER · by provider            │
│  └────────────────────────────┘          (empty if no router.jsonl)      │
│                                                                          │
│  OBSERVE · last run                      TRUST                           │
│  No observe snapshot yet                 untrusted / trusted counts      │
│  (run make observe)                      promotions / demotions          │
└──────────────────────────────────────────────────────────────────────────┘
```

### Sample JSON fragment (`GET /console/data`)

```json
{
  "read_only": true,
  "missing_logs": ["router.jsonl"],
  "decisions": [
    {
      "ts": "2026-07-10T15:40:49.178459",
      "disposition": "proceed",
      "action": "format this file and explain the helper function",
      "rationale": "Forced to ollama (override)",
      "authorized_by": "router:allow:risk=10",
      "provider": "ollama",
      "category": "simple_code"
    },
    {
      "disposition": "escalated",
      "action": "…",
      "authorized_by": "agent:repo_steward"
    }
  ],
  "escalations": [
    {
      "event": "escalation_created",
      "id": "ZLC_C_vfnoo",
      "status": "pending",
      "risk_level": 10
    }
  ],
  "router": { "by_provider": {}, "total": 0, "recent": [] },
  "debrief": {
    "day": "2026-07-10",
    "decision_count_today": 49,
    "dispositions_today": { "proceed": 35, "escalated": 10, "refused": 4 }
  },
  "trust": {
    "by_level": { "untrusted": 1, "trusted": 1, "autonomous": 0 }
  },
  "observe": { "available": false }
}
```

Disposition badges in the UI: **PROCEED** (green), **REFUSED** (red),
**ESCALATED** (amber), **CONTESTED** (purple).

## What it will not do

- No `POST` / `PUT` / `DELETE` under `/console*`
- No spawn, approve, observe-refresh, or steward trigger from this UI
- Missing logs → empty sections, never a hard 500 on `/console/data`

## Tests

```bash
pytest tests/test_console.py -q
```
