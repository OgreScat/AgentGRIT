# Example: Multi-screen Ops Console (read-only)

Local operations UI for the **whole GRIT runtime**. Governance is one module;
screens cover tasks, research, models/cost, audit, and an overview KPI strip.

| Route | Method | Role |
|---|---|---|
| `/console` | GET | Self-contained multi-screen HTML (no CDN) |
| `/console/data?screen=overview\|tasks\|…` | GET | Per-screen JSON rollup |
| `/console/data` or `?screen=flat` | GET | Legacy flat rollup (back-compat) |

**Never acts.** No POST under `/console*`. Approvals stay on CLI / Telegram.

## Run

```bash
python -m src.main --api-only
make console
# Open http://127.0.0.1:8000/console
```

## IA (information architecture)

```
┌─ AgentGRIT Ops · READ-ONLY · Approvals → CLI/Telegram ──────── live ─┐
│ Overview │  KPI strip + recent activity timeline                      │
│ Tasks    │  filterable decision table          │ Context rail        │
│ Governance│ tabs: esc / bylaws / decisions / pillars (thin) │ (selected)│
│ Research │ briefs · contested · observe snapshot                      │
│ Models   │ provider bars · budget thr · why-this-model                │
│ Audit    │ notifications · brief history · decisions · projects stub  │
└──────────────────────────────────────────────────────────────────────┘
```

## Screenshot-in-text per screen

### Overview
```
KPIs: [decisions today: N] [pending esc: N] [router n] [est cost Σ]
      [trust ↑] [trust ↓]  + disposition chips
Last blocked: rm -rf / — Law 0
Recent activity: decision/escalation timeline (newest first)
```

### Tasks
```
filters: disposition ▾  provider ▾
| When | Disp | Action | Provider | Bylaw | Evidence |
| …    | PROCEED | format helpers | ollama | proceed | sufficient |
Row click → right rail: route reason, bylaw, evidence, link to /brief
```

### Governance
```
tabs: [escalations] [bylaws] [decisions] [pillars]
Note: Approvals are NOT available here — console is read-only.
pillars: "No pillars.jsonl yet — intentionally thin."
```

### Research
```
[briefs N] [contested N] [weak/flagged N]
Observe last run (if API has snapshot) · brief list with CONTESTED badges
```

### Models & Cost
```
[routes] [local] [cloud] [est cost Σ]
Budget thresholds from config: soft / escalate / hard
Bars by provider · "Why this model" drawer from router.jsonl reason
```

### Audit
```
Notifications tail · brief history · recent decisions
Projects: honest stub unless decisions carry project keys
```

## Sample: `GET /console/data?screen=overview` (shape)

```json
{
  "read_only": true,
  "screen": "overview",
  "screens": ["overview","tasks","governance","research","models","audit"],
  "kpis": {
    "decisions_today": 12,
    "pending_escalations": 1,
    "router_total": 12,
    "last_blocked": { "action": "rm -rf /", "reason": "…" }
  },
  "timeline": [ { "kind": "decision", "label": "proceed", "text": "…" } ]
}
```

## Data backing (honest)

| Screen | Strong logs | Thin / stub |
|---|---|---|
| Overview | decisions, escalations, trust, router | active agents inferred from `authorized_by` |
| Tasks | decisions (+ router recent) | — |
| Governance | bylaws, escalations, decisions | **pillars** (no `pillars.jsonl`) |
| Research | briefs.jsonl, decision evidence | observe needs in-memory snapshot |
| Models | router.jsonl + config budget thresholds | — |
| Audit | notifications, briefs, decisions | **projects** only if `project` field set |

## Tests

```bash
pytest tests/test_console.py -q
```
