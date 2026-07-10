# Example: Multi-screen Ops Console (read-only) · product-grade layout

Local operations UI for the whole GRIT runtime. **Never acts** — logs only.

| Route | Method |
|---|---|
| `/console` | GET — multi-screen HTML |
| `/console/data?screen=overview\|tasks\|…` | GET — per-screen rollup |
| `/console/data?screen=flat` | GET — legacy flat rollup |

## Run

```bash
python -m src.main --api-only
make console
# http://127.0.0.1:8000/console
```

## Layout (v0.2.5 polish)

```
┌─ AgentGRIT Ops · READ-ONLY · Approvals → CLI/Telegram ──── live · overview ─┐
│ Overview │                                                                  │
│ Tasks    │   ┌─ TODAY ──┐ ┌─ TRUST ──┐ ┌─ ROUTER ─┐ ┌─ LAST BLOCKED ─────┐ │
│ Governance│  │ 12       │ │ ↑0 · ↓0  │ │ 13       │ │ rm -rf /            │ │
│ Research │   │ decisions│ │ promo/dem│ │ routes   │ │ Law 0 …             │ │
│ Models   │   │ esc: 2   │ │          │ │ cost Σ   │ │                     │ │
│ Audit    │   └──────────┘ └──────────┘ └──────────┘ └─────────────────────┘ │
│          │   Recent activity timeline…              │ Context               │
│          │                                          │ TASK                  │
│          │                                          │ DISPOSITION  [PROCEED]│
│          │                                          │ ROUTE REASON          │
│          │                                          │ ┌ mono log block ──┐  │
│          │                                          │ │ cheapest capable │  │
│          │                                          │ └──────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Overview — mission-control cards
Four grouped cards (**Today**, **Trust**, **Router totals**, **Last blocked**) with
value hierarchy (large numbers / secondary sublines), then activity timeline.

### Tasks — app-like filters
Filter bar (disposition · provider) on a panel; clear selected row; table density
kept high. Row → labeled context rail sections.

### Governance — tab chrome
Selected tab: accent underline + filled background; unselected: quiet border.
Pillars remain honestly thin when `pillars.jsonl` is absent.

### Research / Models / Audit
Same screens; spacing/type scale only. Models “why this model” uses mono log
blocks for routing reasons.

## Data backing (unchanged)

| Screen | Strong | Thin |
|---|---|---|
| Overview, Tasks, Models | JSONL | agent count inferred |
| Governance | bylaws / esc / decisions | pillars (no log) |
| Research | briefs | observe needs snapshot |
| Audit | notifications / briefs | projects stub |

## Tests

```bash
pytest tests/test_console.py -q
```
