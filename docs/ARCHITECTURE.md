# GRIT Architecture: Cost-Governance Layer for Dynamic Workflows

> Written June 5, 2026, after Anthropic shipped Dynamic Workflows (May 28, 2026).
> This document supersedes the "GRIT as orchestrator" framing from the v2.x line.

> Note: modules marked CUT below remain in-tree so the legacy orchestrator entry point
> (`src/main.py`) keeps working, but they are frozen -- do not extend them.

## The one-paragraph thesis

Anthropic shipped the orchestration primitive (Dynamic Workflows) natively in Claude Code:
a script Claude writes that fans out up to 1,000 subagents, holds intermediate results in
script variables instead of the context window, verifies findings adversarially, and resumes
after interruption. That is the half of GRIT we were hand-rolling. **We stop building it.**
But Anthropic deliberately did NOT build cost-governance: by design, every subagent uses your
session's model unless the script routes a stage elsewhere, and that routing is decided ad hoc
by Claude per task — there is no systematic policy deciding "is this task worth a 1,000-agent
Opus furnace, or should stages run on Ollama/Perplexity/Haiku?" **That decision is GRIT's
entire reason to exist now.** GRIT becomes the cost-governance + cross-provider-trust wrapper
*around* workflows, not a competitor to them.

## Why this is a stronger position, not a retreat

1. **Anthropic's incentive is the opposite of ours.** Their docs repeatedly warn workflows
   "use meaningfully more tokens." A 1,000-Opus-agent run is a token furnace and they have zero
   incentive to route you away from it. We have every incentive. The more expensive native
   workflows get, the more valuable a cost-governor becomes.
2. **The hook already exists in the platform.** Docs: "Every agent in a workflow uses your
   session's model unless the script routes a stage to a different one... Ask Claude to use a
   smaller model for stages that don't need the strongest one." The routing seam is officially
   supported. We systematize what is currently a manual suggestion.
3. **Our skills travel in for free.** Docs: every spawned agent can still use installed skills.
   So grit-bylaws, cost-optimizer, and capability-map become governance that rides into every
   subagent automatically once installed in `.claude/skills/`.
4. **Our orchestration isn't wasted — it becomes a template.** Docs: "If you already have an
   orchestrator built another way, such as a folder of subagent prompts or a skill that fans
   work out, you can point Claude at it and ask for a workflow that does the same thing." Our
   GRIT agent definitions become workflow seeds.

## Module-by-module verdict

| Module | Verdict | Reason |
|--------|---------|--------|
| `execution/router_v2.py` (2-stage router) | **KEEP — core** | This IS the product now. The classifier + policy layer is what decides per-stage model routing. |
| `execution/capability_map.py` | **KEEP — core** | "Don't ask Ollama to orchestrate" is exactly the judgment a workflow planner needs when assigning models to stages. |
| `execution/verification.py` (`verify_or_fail`) | **KEEP — complementary** | Anthropic's agents verify each other *within Claude*. Our filesystem-truth gate is the only thing that protects you when a cheap local model is in a stage. Defense-in-depth across heterogeneous providers. |
| `governance/bylaws.py` | **KEEP — re-scope** | Block/escalate/notify still matters, but now applies at workflow-plan-approval time: inspect the script before it spawns 1,000 agents. |
| `governance/trust.py` | **KEEP — re-scope** | Trust ladder now decides "auto-approve this workflow plan" vs "escalate to human." Maps cleanly onto the per-mode approval prompts. |
| `skills/*` | **KEEP — ship as-is** | Install into `.claude/skills/`; they ride into every subagent. |
| `bot/telegram.py` | **KEEP — re-purpose** | Mobile control is still the unique value. But it now controls/monitors workflow runs, not a bespoke agent loop. |
| GRIT's bespoke multi-agent coordination / message-passing | **CUT** | Superseded by the workflow runtime (script variables, resumability, adversarial review). Stop maintaining. |
| GRIT's own "spawn agents from scratch" loop | **CUT** | The runtime does this better with hard caps (16 concurrent / 1,000 total). |

## The two new modules this re-position requires

1. **`workflow/planner.py`** — Takes a task description, uses the existing 2-stage classifier
   + capability map to produce a *cost-annotated stage plan*: which stages need Opus, which can
   run on Sonnet/Haiku/Ollama/Perplexity, with a projected token/cost estimate and a cheaper
   alternative. Output is both human-readable (for Telegram approval) and a JSON spec a workflow
   script can consume to route stages.

2. **`workflow/cost_governor.py`** — The policy gate. Given a planned workflow (phase list +
   per-phase model), it (a) estimates spend, (b) flags furnace runs before they start, (c)
   proposes a downgraded plan, (d) enforces a budget ceiling, (e) runs the bylaw check on the
   plan. This is the thing that answers "is this worth it?" before 1,000 agents spawn.

## How it actually plugs in (the honest integration path)

GRIT cannot intercept Anthropic's runtime — it's a closed background process. So GRIT operates
at two real seams:

- **PRE-RUN (plan time):** GRIT generates the cost-annotated plan and the model-routing JSON,
  which you hand to Claude when you describe the workflow ("route stages per this spec"). This
  is fully supported today via the documented per-stage model routing.
- **POST-RUN (verify time):** GRIT's `verify_or_fail` runs against the filesystem/git after the
  workflow reports done, independent of what the agents claimed. Catches the cheap-model-lied
  failure mode that survives on non-Opus stages.

Plus the always-on **SKILLS seam**: governance skills installed once, ride into every agent.

This is not vaporware coupling — every seam maps to a documented, shipping capability. We are
not pretending to hook the runtime internals.

## Money path (why this matters beyond elegance)

The re-positioned GRIT is the thing that makes a heavy-usage plan pay for itself:
- Workflows burn tokens fast. A cost-governor that downgrades non-critical stages is the
  difference between one furnace run and ten governed runs on the same quota.
- Once GRIT reliably governs spend, the same engine can price out any repeatable job:
  a task becomes a governed workflow with a known token budget you can quote against.
- Any multi-step job you would want to rerun as a single command benefits from the same
  pattern — plan once, govern cost, rerun as a command.

## What this does NOT touch

Downstream product codebases. AgentGRIT governs execution -- it doesn't own or modify the applications you build with it. That's a separate concern, shipped separately.

---

## UPDATE (v2.6) — the islands are now wired

The audit that produced this document found that planner/governor/verification
were tested but unwired. v2.6 closes that:

- **`grit.py`** — standalone zero-dep CLI: `govern`, `eval`, `trust`.
- **`src/evals/`** — eval harness (Anthropic transcript-vs-outcome methodology),
  12-task suite grading real governor OUTCOMES, runner that feeds results into
  the trust ladder. 12/12 green.
- **Trust persistence** — `data/trust_state.json`. Trust now ACCUMULATES across
  runs and is EARNED: 5 green eval runs → TRUSTED, 20 → AUTONOMOUS. Autonomy is
  gated by passing evals, exactly per Anthropic's guidance.
- **`src/bot/bot_workflow.py`** — pure, testable Telegram handlers. `/plan <task>`
  renders a cost-annotated approval with Approve/Reject buttons; replaces the
  dead `# TODO: spawn via orchestrator` stub.
- **`src/main.py`** — `--govern` and `--eval` fast-path commands (offline).

Still TODO (needs you at keyboard): calibrate planner constants from a real
workflow's token counts (RUNBOOK Step 7); wire bot_workflow handlers into the
live aiogram dispatcher (currently standalone+tested, not yet attached).

The bespoke orchestrator `grit_agent.py` remains in the tree but is CUT per the
table above — do not extend it; the workflow runtime supersedes it.
