# AgentGRIT -- Project Context for AI Coding Assistants

This file is what Claude Code, Cowork, or any similar tool should read before doing work in this
repository. It describes the architecture, the conventions, and the non-negotiable rules --
not a development diary, and not tied to any one person's projects.

---

## What AgentGRIT Is

A self-governing agent framework: cost-first LLM routing, a bylaws engine that agents enforce on
themselves, a trust ladder that gates autonomy on track record, and a two-person-integrity
escalation system for anything genuinely risky. It ships as a framework with empty templates,
not a working agent for any specific business -- see `src/agents/example_agent.py` and
`src/governance/persona.py` for the fill-in-your-own-project pattern.

Two entry points exist and serve different purposes:

- `python -m src.main` -- the agent orchestrator, API server, and Telegram bot. This is where
  any agents you register actually run.
- `python grit.py govern "<task>"` -- a standalone cost-governance CLI that plans a task, decides
  which model tier it's worth, and verifies the outcome afterward, independent of whatever
  actually executes it.

---

## Core Principles

1. **Cost-first routing** -- classify the task, route to the cheapest capable LLM. Ollama (free,
   local) for simple work; cloud providers only when the task actually needs their capability.
   See `src/execution/router.py` (used by the agent orchestrator) and `src/execution/router_v2.py`
   (used by the workflow/cost-governance layer under `src/workflow/`).

2. **Self-governing, not approval-gated** -- the bylaws engine (`src/governance/bylaws.py`)
   blocks destructive patterns outright, requires verification before code changes are considered
   done, and escalates genuine risk. It does not ask permission for routine work.

3. **Zeroth Law** -- an agent must not, through silence or inaction, allow a foreseeable harm to
   the human's interests, the project's integrity, or anyone's safety to go unreported. Finding a
   real risk and not mentioning it is its own failure mode. This is why
   `src/governance/bylaws.py` has a `repo_publish` `EscalationTrigger`: an earlier self-grade
   found that publishing a repository publicly triggered zero escalation under the original
   rules, so the gap became a permanent rule rather than a one-off fix. That's the standing
   discipline -- see `docs/POSTMORTEM.md`.

4. **Trust is earned, not assumed** -- `UNTRUSTED → TRUSTED → AUTONOMOUS`, promoted by consecutive
   successes, demoted by any failure. `src/governance/model_provenance.py` is the lineage gate
   that decides whether a given model is even eligible to enter the ladder.

5. **Escalation has teeth** -- `docs/ESCALATIONS.md` describes the real flow: Worker proposes,
   BylawEngine evaluates (PROCEED / ESCALATE / BLOCK), a deterministic non-LLM Manager evaluates
   escalations, and high/critical risk requires your explicit approval over Telegram. A
   break-glass identity can view escalations but never approve them.

---

## Where Things Live

```
src/main.py                     CLI entry point (API + Telegram + agent orchestrator)
src/config.py                   Pydantic settings, .env-driven
src/agents/example_agent.py     Template agent -- copy this, don't extend it in place
src/agents/grit_agent.py        Core agent loop: router + bylaws + memory integration
src/execution/router.py         Cost-first routing for the main agent orchestrator
src/execution/router_v2.py      Routing for the workflow/cost-governance layer
src/governance/bylaws.py        Bylaw engine, roles, escalation triggers, Zeroth Law doctrine
src/governance/escalations.py   Two-person-integrity escalation flow
src/governance/trust.py         Trust-ladder state machine
src/governance/persona.py       Empty ProjectSoul template -- register your own real projects here
src/governance/personas.py      Generic expert-persona library (prompt framing, not project identity)
src/governance/context_loader.py  Per-project context loading; escalates rather than proceeding blind
src/workflow/                   Cost-governance layer wrapping Dynamic-Workflow-style runs
src/evals/                      Trust-ladder eval harness (transcript-vs-outcome grading)
src/bot/telegram.py             Telegram control surface
src/api/server.py               FastAPI server
grit.py                         Standalone cost-governance CLI
tests/                          Pytest suite
docs/                           ESCALATIONS.md, OLLAMA-SETUP.md, QUICKSTART.md, POSTMORTEM.md
QUICKSTART-AGENTS.md            How to register and run your own agents
GRIT-LEADER-PLAYBOOK.md         Leader/builder/verifier workflow pattern for multi-agent work
```

Note the deliberate split between `persona.py` (singular -- which real project this agent is
working for) and `personas.py` (plural -- which expert framing improves this prompt). They solve
different problems; neither is dead code left over from the other.

---

## Conventions

- **Never silently proceed on missing context.** `context_loader.load_project_context()` returns
  the literal string `"NO_PROJECT_CONTEXT_FOUND"` for an unconfigured project rather than an
  empty string, specifically so callers have something concrete to escalate on.
- **Evidence over claims.** A task is "done" when there's a real, re-runnable result to point to
  (tests passing, a diff, a log line) -- not when an agent says it's done. See
  `GRIT-LEADER-PLAYBOOK.md`'s "finish lines that can't be faked."
- **New risk found → new rule, not just a patch.** When a real gap is discovered (in an audit,
  a self-grade, or a failure), the standing discipline is: write it up, encode the fix as a
  Bylaw or `EscalationTrigger`, and cite it in the next audit. See `docs/POSTMORTEM.md`.
- **Agents are registered, not built into the framework.** Nothing in `src/agents/` beyond
  `example_agent.py` should assume a specific business, vertical, or client. If you're adding a
  concrete agent for your own project, register it in `AVAILABLE_AGENTS` in `src/main.py`, but
  keep the framework itself generic.

---

## Testing

```bash
pytest                    # full suite
make test-imports         # catches import regressions
make agentgrit-smoketest  # router + bylaws smoke test, no external dependencies
ruff check . && black --check .
mypy src/
```

---

## Reference Docs

- `docs/ESCALATIONS.md` -- the two-person-integrity escalation system in full.
- `docs/POSTMORTEM.md` -- the post-mortem-to-rule discipline, with the `repo_publish` trigger as
  the canonical example.
- `docs/AGENT-SCOPE-TEMPLATE.md` -- fill this in before registering a new agent.
- `QUICKSTART-AGENTS.md` -- end-to-end walkthrough for registering and running an agent.
- `GRIT-LEADER-PLAYBOOK.md` -- the leader/builder/verifier pattern for multi-agent work.
- `docs/ARCHITECTURE.md` -- the cost-governance rationale (why routing + verification pays for itself).
