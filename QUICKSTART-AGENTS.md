# AgentGRIT Multi-Agent System - Quick Start

**Register your own agents and get them running in 5 minutes.**

> Three quickstarts, three jobs — this one is **registering your own agents**.
> For the always-on observer loop, see [`docs/QUICKSTART.md`](docs/QUICKSTART.md).
> For wrapping a coding agent's workflow in cost governance, see
> [`src/workflow/QUICKSTART.md`](src/workflow/QUICKSTART.md).

## What You're Getting

AgentGRIT ships as a framework, not a set of working agents. Out of the box you get:

- **`src/agents/example_agent.py`**: a `TemplateAgent` you copy and extend -- it already wires
  up bylaws evaluation and persona rendering, so you only need to fill in `run_once()`.
- **`src/main.py`**: a CLI entry point (`AgentOrchestrator`) that starts your registered agents
  on whatever schedule you give them, alongside the API server and Telegram bot.
- **Telegram Bot**: receive updates and send commands from your phone.

This guide walks through registering one example agent and running it. Swap in your own agents
and schedules once you understand the shape.

---

## Prerequisites Check

Run these commands to verify:

```bash
# 1. Ollama is running (if you're using a local model)
curl http://localhost:11434/api/tags

# 2. You're in the AgentGRIT directory
cd /path/to/AgentGRIT
pwd

# 3. Your .env has Telegram configured (optional, only if you want bot control)
grep TELEGRAM_BOT_TOKEN .env
```

If any fail, see "Troubleshooting" section below.

---

## Installation (One-Time Setup)

```bash
cd /path/to/AgentGRIT

# Install all dependencies
make install-deps

# This installs:
# - playwright (browser automation, if your agents need it)
# - requests (API calls)
# - aiogram (Telegram bot framework)
# - Chromium browser (for testing)
```

**Expected output:**

```
Installing AgentGRIT dependencies...
✓ Dependencies installed
```

---

## Register an Agent

Open `src/main.py` and find `AgentOrchestrator.AVAILABLE_AGENTS`. Add an entry pointing at your
agent (copy `src/agents/example_agent.py` as a starting point, or register the template as-is to
confirm the plumbing works):

```python
AVAILABLE_AGENTS = {
    "example": "Template agent -- copy src/agents/example_agent.py to build your own",
    "your_agent": "One-line description of what it does",
}
```

Then wire `start_agent()` to actually instantiate it, following the pattern already used for
`"example"`.

**Before you register it for real:** fill in `docs/AGENT-SCOPE-TEMPLATE.md` (trigger, inputs,
steps, escalation conditions, success criteria -- a few minutes, not a design doc), then run
an edge-case stress test against your own scope: ask an LLM to list 10 real-world edge cases
that could break this agent's logic, ranked by likelihood, with a handling rule for each. Both
steps are cheap now and expensive to skip once the agent is running unattended.

---

## Launch

```bash
cd /path/to/AgentGRIT

# Start all services (API + Telegram + registered agents)
make run-agents

# Or run just one agent, foreground:
python -m src.main --agent your_agent
```

**You'll see:**

```
🚀 AgentGRIT Multi-Agent System
============================================================
Agents:
  ├─ your_agent (your schedule here)
  └─ Telegram Bot (always-on, if configured)
============================================================
```

If Telegram is configured, you'll receive a startup notification within 30 seconds.

---

## Interacting via Telegram

### Available Commands

| Command | What It Does |
|---------|-------------|
| `/status` | Check system status |
| `/spawn <task>` | Manually spawn a new task |
| `/digest` | Get current digest summary |
| `/health` | System health check |
| `/trust` | View trust levels |
| `/plan <task>` | Ask GRIT to plan a task before running it |

### Natural Language

Just type what you want:

```
"add input validation to the signup form"
"fix the linting errors in the auth module"
```

The bot will parse your intent and create tasks.

---

## Checking Logs

```bash
# View a specific agent's log (name depends on what your agent writes)
cat logs/your_agent_events.jsonl | jq

# Live tail all logs
make tail
```

---

## Stopping Agents

```bash
# Stop all agents gracefully
make stop-agents
```

You'll get a Telegram notification if the bot is configured.

---

## Safety Features to Build In

These aren't automatic -- they're the pattern the bylaws engine expects your agents to follow.
Copy this checklist for each agent you register:

- ✅ Start in **dry-run mode** by default (`settings.dry_run`, see `src/config.py`) --
  agents log what they would do before they're allowed to act for real.
- ✅ Route every action through `BylawEngine.evaluate()` (see `src/agents/example_agent.py`)
  so BLOCK/ESCALATE decisions are enforced, not just suggested.
- ✅ Cap anything with a real-world cost (trades, spend, destructive file operations) with an
  explicit limit and a circuit breaker (e.g. "stop after N consecutive failures").
- ✅ Only operate on data/sources you're licensed or permitted to use.
- ✅ Log every decision to `logs/` so a human can audit it after the fact.

---

## Troubleshooting

### "Telegram bot failed"

```bash
# Check .env has a valid token
cat .env | grep TELEGRAM_BOT_TOKEN

# Get a token from @BotFather on Telegram if missing
```

### "Playwright not available"

```bash
# Reinstall
pip install playwright
playwright install chromium
```

### "Ollama connection refused"

```bash
# Start Ollama server
ollama serve &

# Verify it's running
curl http://localhost:11434/api/tags
```

### Agents not doing anything

```bash
# Check logs for errors
make tail
```

Also confirm your agent is actually listed in `AgentOrchestrator.AVAILABLE_AGENTS` and that
`start_agent()` knows how to instantiate it -- an unregistered `--agent` name is a no-op by
design, not a silent failure you have to guess at (see `src/main.py`'s `run_agents()`).

---

## Next Steps

1. **Monitor for 24 hours**: let your agent run and watch Telegram updates.
2. **Review logs**: check accuracy against what you expected.
3. **Tune thresholds**: adjust whatever limits you built into the agent.
4. **Add more agents**: repeat the registration steps above for each one.
5. **Move off dry-run**: only after you trust the logs, flip `DRY_RUN=false` in `.env`.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                   AgentGRIT Multi-Agent System                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  your_agent  │  │  your_agent  │  │  (add more   │          │
│  │      #1      │  │      #2      │  │   as needed) │          │
│  │              │  │              │  │              │          │
│  │  your sched  │  │  your sched  │  │              │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│         │                 │                  │                  │
│         └─────────────────┴──────────────────┘                  │
│                           │                                     │
│                           ▼                                     │
│                  ┌─────────────────┐                            │
│                  │  Orchestrator   │                            │
│                  │  + Telegram Bot │                            │
│                  └─────────────────┘                            │
│                           │                                     │
│                           ▼                                     │
│                       You (Telegram)                            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

**You're ready to go. Register an agent, run `make run-agents`, and let it work while you sleep.**
