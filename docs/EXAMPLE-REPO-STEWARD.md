# Example: Repo Steward end-to-end

This is AgentGRIT's first **turnkey** agent — a governed *advisor* that
composes existing primitives. It does **not** edit files.

| Primitive | Role |
|---|---|
| `gardener.tend()` | Real hygiene findings (secrets, large files, MEMORY.md, …) |
| `skill_discovery.discover_local()` | Propose local skills (install nothing) |
| `autonomy.classify_action_risk` + `decide` + `must_stop` | Gate each proposed remediation |
| `decision_record.record(..., authorized_by="agent:repo_steward")` | One auditable record per run |

## How to run

```bash
# One-shot on the current tree
make agent-steward DIR=.

# Equivalent CLI
python -m src.agents.repo_steward_agent .

# Via orchestrator (scheduled loop; dry-run safe)
python -m src.main --agent repo_steward --dry-run
```

---

## Sample A — dogfood on this public repo

Command: `python -m src.agents.repo_steward_agent .`

```
REPO STEWARD REPORT  ·  governed advisor (no auto-edit)
========================================================
  root:     .
  status:   done
  findings: 1  (worst=MEDIUM)
  decision: proceed

FINDINGS & PROPOSED ACTIONS
--------------------------------------------------------
  1. [MEDIUM/knowledge_present] MEMORY.md
     detail:   MEMORY.md missing at repo root -- memory layer has no anchor
     propose:  report missing knowledge file MEMORY.md: create MEMORY.md after review
     autonomy: ✓ advice  gate=require_briefing risk=10 — UNTRUSTED trust -- inform human before/as acting on LOW risk

LOCAL SKILLS (propose-only, not installed)
--------------------------------------------------------
  (none matched)

NOTES
--------------------------------------------------------
  • Mode: governed advisor — zero file mutations in this version.
  • Target: .

This agent does NOT edit files. Apply escalated remediations only after human approval.
========================================================
```

### Decision record (same run)

Appended to `logs/decisions.jsonl` with `authorized_by: "agent:repo_steward"`:

```json
{
  "action": "repo_steward inspect .",
  "disposition": "proceed",
  "rationale": "steward tend(.): 1 findings, 0 escalated",
  "chosen_provider": "local",
  "category": "repo_steward",
  "confidence": 1.0,
  "estimated_cost_usd": 0.0,
  "bylaw_action": "proceed",
  "evidence": {
    "verdict": "sufficient",
    "require_human": false,
    "reason": "0 remediation(s) require human approval; steward does not auto-edit"
  },
  "authorized_by": "agent:repo_steward"
}
```

**Where autonomy escalated:** nowhere on this run. The only finding is a
report-only advice action (`create MEMORY.md after review`). Risk=LOW.
Trust for pattern `repo_steward` was still UNTRUSTED, so the gate is
`require_briefing` (proceed after record — not a hard stop). No
destructive remediation was proposed.

---

## Sample B — planted secrets + large file (escalation path)

Fixture (what the unit tests plant): a doc with a secret-shaped line, a 2MB
blob, and a MEMORY.md. Command equivalent:

```bash
# conceptual — tests use tmp_path + GardenConfig(large_file_mb=1.0)
python -m src.agents.repo_steward_agent /path/to/fixture
```

```
REPO STEWARD REPORT  ·  governed advisor (no auto-edit)
========================================================
  root:     steward-docs-sample
  status:   done
  findings: 3  (worst=HIGH)
  decision: escalated

FINDINGS & PROPOSED ACTIONS
--------------------------------------------------------
  1. [HIGH/secrets_in_docs] NOTES.md
     detail:   aws access key pattern found in a tracked document
     propose:  delete secrets from NOTES.md and rotate the leaked credentials (...)
     autonomy: ⤴ ESCALATE  gate=escalate risk=30 — bylaw requires human decision

  2. [HIGH/secrets_in_docs] NOTES.md
     detail:   secret assignment pattern found in a tracked document
     propose:  delete secrets from NOTES.md and rotate the leaked credentials (...)
     autonomy: ⤴ ESCALATE  gate=escalate risk=30 — bylaw requires human decision

  3. [LOW/large_file] blob.bin
     detail:   2 MB inside the repo (stale backup / dead weight?)
     propose:  rm -rf blob.bin to reclaim disk (...)
     autonomy: ⤴ ESCALATE  gate=deny risk=30 — bylaw hard block

...
This agent does NOT edit files. Apply escalated remediations only after human approval.
========================================================
```

### Where autonomy escalated (and why)

| Proposal | Risk classifier | Bylaw | Autonomy gate | Result |
|---|---|---|---|---|
| `delete secrets … and rotate the leaked credentials` | HIGH (30) — `rotate` + `secrets` | ESCALATE (security patterns) | **escalate** | `must_stop` → not applied |
| `rm -rf blob.bin …` | HIGH (30) — `rm -rf` | **BLOCK** (absolute destructive) | **deny** | `must_stop` → not applied |

Run disposition = **escalated** because at least one remediation requires a human.
The steward still only *reports* — it never executes delete/rotate/rm.

Decision record (abridged):

```json
{
  "action": "repo_steward inspect steward-docs-sample",
  "disposition": "escalated",
  "bylaw_action": "escalate",
  "evidence": {
    "verdict": "insufficient",
    "require_human": true,
    "reason": "3 remediation(s) require human approval; steward does not auto-edit"
  },
  "authorized_by": "agent:repo_steward"
}
```

---

## What this does *not* do

- Does not rewrite, delete, or commit files.
- Does not call cloud LLMs (provider=`local`, cost=`0.0`).
- Does not install skills — discovery is propose-only.
- Does not replace `make garden` / nightly gardener; it *uses* the same `tend()`.

## Tests

```bash
pytest tests/test_repo_steward.py -q
```
