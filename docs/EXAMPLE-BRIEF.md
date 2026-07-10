# Example: Governed brief UI (domain user surface)

The **operator console** (`/console`) shows the raw governance stream.  
The **brief UI** (`/brief`) renders **one agent run** as a trustable briefing for a
non-operator: answer framing, confidence band, **verified citations only**,
CONTESTED banner, judgment checklist, disposition + autonomy gate.

Read-only. Agents may append `logs/briefs.jsonl` via `brief_record.record_brief`;
the UI only **reads**.

## Run

```bash
python -m src.main --api-only   # if not already up
make brief
# Open:  http://127.0.0.1:8000/brief
# Data:  http://127.0.0.1:8000/brief/data?run=latest&profile=generic
# Legal labels (sample profile):  .../brief/data?profile=legal
```

## Same run · generic profile

`GET /brief/data?run=latest&profile=generic` (planted legal_research envelope):

```json
{
  "kind": "legal_research",
  "question": "case law research for counsel: qualified immunity at summary judgment",
  "disposition": "proceed",
  "confidence_score": 0.86,
  "confidence_band": "strong",
  "dropped_count": 1,
  "contested": false,
  "authorities": [
    {
      "title": "Pearson v. Callahan",
      "url": "https://www.courtlistener.com/opinion/145930/pearson-v-callahan/",
      "citation": "555 U.S. 223",
      "verified": true
    }
  ],
  "needs_judgment": [
    "Confirm jurisdiction and controlling circuit.",
    "Read the full opinion before relying."
  ],
  "profile": {
    "id": "generic",
    "title": "Governed brief",
    "judgment_label": "Needs human judgment",
    "disclaimer": "Advisory only. Verify before acting. Not a substitute for professional judgment.",
    "contested_label": "CONTESTED evidence"
  },
  "read_only": true
}
```

### Screenshot-in-text (generic)

```
┌─ Governed brief · READ-ONLY · verified citations only ──── profile: generic ─┐
│ Advisory only. Verify before acting. Not a substitute for professional…      │
│                                                                              │
│  [PROCEED]  kind=legal_research · gate=allow · ollama                        │
│                                                                              │
│  case law research for counsel: qualified immunity at summary judgment       │
│                                                                              │
│  confidence · strong                                              score 0.86 │
│  ████████████████████████████████████████░░░░                                │
│                                                                              │
│  AUTHORITIES (verified only · dropped=1)                                     │
│  1. Pearson v. Callahan                                                      │
│     555 U.S. 223                                                             │
│     https://www.courtlistener.com/opinion/…/pearson-v-callahan/              │
│                                                                              │
│  NEEDS HUMAN JUDGMENT                                                        │
│  • Confirm jurisdiction and controlling circuit.                             │
│  • Read the full opinion before relying.                                     │
│                                                                              │
│  (Dropped/uncited claims are counted, never shown as clickable authorities.) │
└──────────────────────────────────────────────────────────────────────────────┘
```

Note: `dropped_count: 1` (“Unverified blog claim”) appears only as a count —
**not** as a clickable authority.

## Same run · legal profile (labels only)

`GET /brief/data?run=latest&profile=legal` — **same authorities and disposition**;
only the profile dict swaps:

| Field | generic | legal (sample) |
|---|---|---|
| `title` | Governed brief | Legal research briefing |
| `judgment_label` | Needs human judgment | Needs attorney judgment |
| `disclaimer` | Advisory only… | Not legal advice. Verify before filing. |
| `contested_label` | CONTESTED evidence | CONTESTED authority |

```
┌─ Legal research briefing · READ-ONLY ──────────────────── profile: legal ───┐
│ Not legal advice. Verify before filing.                                      │
│ … same PROCEED / Pearson citation / dropped=1 …                              │
│ NEEDS ATTORNEY JUDGMENT                                                      │
│  • Confirm jurisdiction and controlling circuit.                             │
└──────────────────────────────────────────────────────────────────────────────┘
```

No legal-specific strings live in the default HTML or `GENERIC_PROFILE`.  
The `legal` profile is a **sample override** for private/domain layers.

## Adapters

| Agent envelope | Adapter maps |
|---|---|
| `legal_research` | authorities (verified URLs only), dropped→count, contested, needs_attorney, autonomy_gate |
| `repo_steward` | proposals→needs_judgment (escalated remediations), no fake URLs |
| `observe` | actionable events with URLs→authorities; non-actionable→needs_judgment |
| unknown | generic fallback |

## What it will not do

- No POST/PUT/DELETE under `/brief*`
- Never render an unverified URL as an authority
- Never invent citations when `briefs.jsonl` is missing (empty state or decision-row fallback without fake links)

## Tests

```bash
pytest tests/test_brief.py -q
```
