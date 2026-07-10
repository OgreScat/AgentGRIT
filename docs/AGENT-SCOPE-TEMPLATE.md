# Agent Scope Template

Fill this in before you register a new agent in `AVAILABLE_AGENTS` (`src/main.py`). It's meant
to be quick -- a few minutes, not a design doc -- but writing it down before you write `run_once()`
catches vague scope early, when it's cheap to fix.

Copy this file (or just this section) per agent and keep the filled-in version wherever your
project's own docs live -- it doesn't need to go back into this template.

---

## Agent name

`your_agent_name` (matches the key you'll use in `AVAILABLE_AGENTS`)

## Trigger

What starts a run? A schedule (`cron`-style interval), an incoming event (webhook, message,
file change), or a manual `--agent your_agent_name` invocation? Be specific about cadence if
it's scheduled -- "every 2 hours" is a decision, not a default.

## Inputs

What does the agent need to do its job, and where does each thing come from? List concrete
sources: an API, a file path, a database table, a message from Telegram. If a value must come
from `.env`, name the variable.

## Steps

Write the logic as a numbered, if-this-then-that flow wherever possible -- the same shape as
`TemplateAgent.run_once()` in `src/agents/example_agent.py`. If a step can't be reduced to a
rule, say so explicitly rather than hand-waving it as "the agent figures it out."

## Escalation conditions

Under what conditions should this agent stop and hand off to a human instead of proceeding?
At minimum, confirm how it plugs into the existing bylaws (`BylawEngine.evaluate()`) rather than
inventing a parallel check -- see `docs/ESCALATIONS.md`. Name the specific triggers that apply:
cost above a threshold, an unfamiliar data shape, a destructive action, anything outside a
documented safe range.

## Success criteria

What does "this run worked" actually look like, in a form you could check without trusting the
agent's own claim? A specific log line, a file that exists, a test that passes, a value in a
known range. If you can't write this down concretely, the agent isn't ready to register yet.

## Known limitations

What will this agent predictably get wrong or refuse to handle in its first version? Write these
down now -- it's the difference between a known gap and a surprise later, and it's exactly the
kind of thing an edge-case stress test (see `QUICKSTART-AGENTS.md`) should be run against before
you trust this agent with anything unattended.
