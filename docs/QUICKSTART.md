# Observer Loop Quickstart

**Get the always-on heartbeat running in 5 minutes. No ambiguity.**

> Three quickstarts, three jobs — this one is the **observer loop** (a continuous
> heartbeat exercising router + bylaws). To register and run **your own agents**,
> see [`../QUICKSTART-AGENTS.md`](../QUICKSTART-AGENTS.md). To wrap a **coding
> agent's workflow** in cost governance, see
> [`../src/workflow/QUICKSTART.md`](../src/workflow/QUICKSTART.md).

---

## Run AgentGRIT Observer (Always-On Loop)

Start the continuous heartbeat loop that exercises router + bylaws.

### Canonical Command

```bash
cd /path/to/AgentGRIT
make run
```

This is the **official** way to run AgentGRIT. It:

- Sets `PYTHONPATH=.` automatically
- Starts the observer loop (heartbeat every 30s)
- Logs to `logs/heartbeat.jsonl`

**Stop:** `Ctrl+C` or `make stop`
**View logs live:** `make tail`

---

## Run AgentGRIT Smoketest

Verify the router and bylaws work without any external dependencies.

### One Command

```bash
cd /path/to/AgentGRIT
make agentgrit-smoketest
```

> **Note:** Always use `make` commands. They set `PYTHONPATH=.` so imports work correctly.
> Running `python scripts/...` directly will fail.

### Expected Output

```
AgentGRIT Smoketest
====================

[1] Testing capability-based router...
    Task: "Summarize this article and list the key risks"
    Provider: perplexity
    Category: research
    Confidence: 0.9
    Capabilities: ['web_search']
    Reason: Task requires: web_search | Cheapest provider with web_search
    ✅ Router working

[2] Testing bylaw engine (developer role)...
    Command: "rm -rf /"
    Action: block
    Reason: Blocked by Law 0: Recursive delete from root or home
    ✅ Bylaws blocking dangerous commands

[3] Testing role-based capability check...
    Role: observer
    Action: bash
    Result: block (Role observer cannot perform bash)
    ✅ Role enforcement working

Logs written to:
  - logs/router.jsonl
  - logs/bylaws.jsonl

All tests passed.
```

---

## Run Your Own Agent

AgentGRIT ships with a template, not a working agent -- see `src/agents/example_agent.py`.
Copy it, give it a real `run_once()`, and register it in
`src/main.py`'s `AgentOrchestrator.AVAILABLE_AGENTS`. Then:

```bash
python -m src.main --agent your_agent_name
```

See `QUICKSTART-AGENTS.md` for the full walkthrough (scheduling, logs, safety patterns).

---

## File Locations

| Component | Path |
|-----------|------|
| AgentGRIT Core | `src/` |
| Router | `src/execution/router.py` |
| Bylaws | `src/governance/bylaws.py` |
| Persona / project templates | `src/governance/persona.py`, `src/governance/context_loader.py` |
| Example agent | `src/agents/example_agent.py` |
| Logs | `logs/` |

---

## All Make Commands

```bash
make help          # Show all commands
make run           # Start observer loop (canonical run command)
make tail          # Live view of all logs
make stop          # Stop observer
make status        # Check if observer is running
make test-imports  # Verify imports work (catches regressions)
make agentgrit-smoketest  # Run router + bylaws tests
make run-agents    # Start all services (API + Telegram + registered agents)
make install       # Optional: pip install -e . (alternative to PYTHONPATH)
```

---

## Next Steps

- **With Ollama**: See `docs/OLLAMA-SETUP.md` for local LLM setup
- **Full API**: Run `PYTHONPATH=. python -m src.main --api-only` for FastAPI server
- **Escalations**: See `docs/ESCALATIONS.md` for how the bylaws engine surfaces risk
- **Register your first agent**: See `QUICKSTART-AGENTS.md`
