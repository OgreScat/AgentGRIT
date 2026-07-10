# GRIT × Dynamic Workflows — Quickstart

> Three quickstarts, three jobs — this one is **wrapping a coding agent's
> workflow in cost governance**. To register your own agents, see
> [`../../QUICKSTART-AGENTS.md`](../../QUICKSTART-AGENTS.md). For the always-on
> observer loop, see [`../../docs/QUICKSTART.md`](../../docs/QUICKSTART.md).

GRIT is now a **cost-governance layer** that wraps Claude Code's Dynamic Workflows.
It doesn't orchestrate agents (the runtime does that). It decides, before a run,
*which model each stage should use and whether the run is worth it* — then verifies
the result after, independent of what the agents claimed.

## The 3 seams GRIT operates on

```
                YOU describe a task
                        │
            ┌───────────▼────────────┐
   SEAM 1   │  GRIT planner+governor  │   ← PRE-RUN (this package)
 (pre-run)  │  → cost-annotated plan  │
            │  → model routing spec   │
            │  → approve / downgrade  │
            └───────────┬────────────┘
                        │ hand routing spec to Claude
            ┌───────────▼────────────┐
            │  Claude Code Dynamic    │   ← Anthropic's closed runtime
            │  Workflow runtime       │     (we don't touch internals)
            │  (up to 1000 subagents) │
            └───────────┬────────────┘
                        │ run reports "done"
            ┌───────────▼────────────┐
   SEAM 3   │  GRIT verify_or_fail    │   ← POST-RUN (verification.py)
 (post-run) │  filesystem/git truth   │
            └─────────────────────────┘

SEAM 2 (always-on): governance skills in .claude/skills/ ride into every subagent.
```

## Seam 1 — plan & govern before you run

```python
from src.workflow.cost_governor import govern_task, GovernorConfig

decision = govern_task(
    "Research the top 10 DeFi protocols by TVL and cross-check their security audits",
    GovernorConfig(trust_level="UNTRUSTED"),
)

print(decision.verdict.value)          # allow | downgrade | escalate | block
chosen = decision.downgraded_plan or decision.plan
print(chosen.human_readable())
print(chosen.routing_spec())           # JSON to hand Claude
```

Then in Claude Code, describe the workflow and paste the routing spec:

```
ultracode: Research the top 10 DeFi protocols by TVL and cross-check their
security audits. Route stages per this spec — use the named model for each stage,
do not default everything to the session model:

{"stage_models": [
  {"stage": "Research & source-gathering", "model": "perplexity"},
  {"stage": "Security audit", "model": "claude-opus"},
  {"stage": "Review changes", "model": "claude-haiku"},
  {"stage": "Adversarial cross-check", "model": "claude-opus"}
]}
```

Why this works: Claude Code docs state every subagent uses your session model
*unless the script routes a stage elsewhere*, and explicitly support asking for a
smaller model on stages that don't need the strongest one. GRIT decides that
systematically instead of leaving it to chance.

## Seam 2 — governance skills ride along

Install GRIT's skills once:

```bash
cp -r skills/grit-bylaws        ~/.claude/skills/
cp -r skills/cost-optimizer     ~/.claude/skills/
cp -r skills/capability-map     ~/.claude/skills/   # if present
```

Every subagent a workflow spawns can use installed skills, so your bylaws and
cost rules travel into the fleet automatically.

## Seam 3 — verify after the run

Never trust "done" from a stage that ran on a cheap model. After the workflow
reports completion:

```python
from src.execution.verification import ToolVerifier

v = ToolVerifier(workspace="/path/to/repo")
# Confirm the migration actually produced the files it claimed:
v.verify_file_created("src/app/main_fastapi.py", min_size=200)
v.verify_git_changes(min_changed_files=10)
v.verify_tests_pass()           # ground truth, not self-report
```

Opus 4.8 is far less likely to fake progress than older models, but cheap local
stages still can — so the filesystem-truth gate stays on for non-Opus stages.

## Telegram approval (mobile sign-off)

`decision.telegram_payload()` returns a compact dict with verdict, cost, savings,
per-stage models, and a `needs_human` flag — render it with approve/reject buttons.
The trust ladder (UNTRUSTED → TRUSTED → AUTONOMOUS) controls whether ESCALATE
verdicts require a tap or auto-run.

## Where the money is

- A governed plan turns one $6.48 all-Opus furnace into a $3.29 mixed run —
  same hard stages, cheaper soft ones. On a Max plan that's the difference between
  one run and two on the same quota.
- The same engine prices client work: "build a site for the corner bakery" becomes
  a workflow with a known token budget you can quote against and rerun as a saved
  command.
```
