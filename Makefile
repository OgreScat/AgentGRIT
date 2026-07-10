# AgentGRIT Makefile
# Run "make help" for available commands.

.PHONY: help install test-imports agentgrit-smoketest logs-dir clean-logs run tail stop status run-agents stop-agents install-deps debrief idea-project skills-find agent-steward agent-legal observe console brief

# Python with PYTHONPATH set to project root (makes `from src.` work)
# Use .venv (canonical virtualenv for this project)
ifeq ($(wildcard .venv/bin/python),)
    PYTHON := PYTHONPATH=. python3
else
    PYTHON := PYTHONPATH=. .venv/bin/python
endif

# Default target
help:
	@echo "AgentGRIT Commands"
	@echo "=================="
	@echo ""
	@echo "  make run-agents            🚀 Start all services (API + Telegram + registered agents)"
	@echo "  make stop-agents           Stop a backgrounded run-agents-bg process"
	@echo "  make run                   Start observer loop only (Ctrl+C to stop)"
	@echo "  make tail                  Live view of all logs"
	@echo "  make stop                  Stop running observer"
	@echo "  make status                Check if observer is running"
	@echo ""
	@echo "  make install-deps          Install all required dependencies"
	@echo "  make install               Install package in editable mode (optional)"
	@echo "  make test-imports          Verify all imports work correctly"
	@echo "  make agentgrit-smoketest   Run router + bylaws smoke test with logging"
	@echo ""
	@echo "  make logs-dir              Create logs directory"
	@echo "  make clean-logs            Clear all log files"
	@echo "  make debrief               Daily debrief from audit logs (optional NOTIFY=1)"
	@echo "  make idea-project IDEA=... Scaffold projects/<slug> from an idea"
	@echo "  make skills-find TASK=...  Propose local skills for a task"
	@echo "  make agent-steward DIR=... Run Repo Steward advisor on DIR (default: .)"
	@echo "  make agent-legal Q=...     Legal research advisor (public-record; attorney-tool)"
	@echo "  make observe               GRIT Observe scored feeds (FEED=usgs_earthquakes optional)"
	@echo "  make observe-fixture       Observe from offline fixtures (no network)"
	@echo "  make console               Print URL for read-only operator console (API must be up)"
	@echo "  make brief                 Print URL for domain governed-brief UI (read-only)"
	@echo ""
	@echo "Logs written to:"
	@echo "  - logs/router.jsonl"
	@echo "  - logs/bylaws.jsonl"
	@echo "  - logs/heartbeat.jsonl"
	@echo "  - logs/decisions.jsonl"
	@echo ""
	@echo "No agents ship registered out of the box -- see src/agents/example_agent.py"
	@echo "and src/main.py's AgentOrchestrator.AVAILABLE_AGENTS to add your own."
	@echo "Private GM cron (if any) lives outside this public repo; point it at make debrief."

# Install in editable mode (alternative to PYTHONPATH approach)
install:
	@pip install -e .

# Run AgentGRIT smoke test
agentgrit-smoketest: logs-dir
	@$(PYTHON) scripts/smoketest.py

# Test that all imports work (catches import regressions)
test-imports:
	@$(PYTHON) scripts/test_imports.py

# Create logs directory
logs-dir:
	@mkdir -p logs

# Clear log files
clean-logs:
	@rm -f logs/*.jsonl
	@echo "Logs cleared"

# Run observer loop (continuous heartbeat) - CANONICAL RUN COMMAND
run: logs-dir
	@$(PYTHON) scripts/run_observer.py

# Live tail of all logs
tail:
	@$(PYTHON) scripts/tail_logs.py

# Stop observer (reads PID from logs/observer.pid)
stop:
	@if [ -f logs/observer.pid ]; then \
		pid=$$(cat logs/observer.pid); \
		if kill -0 $$pid 2>/dev/null; then \
			kill $$pid; \
			echo "Observer (PID $$pid) stopped"; \
		else \
			echo "Observer not running (stale PID file)"; \
			rm -f logs/observer.pid; \
		fi; \
	else \
		echo "No observer PID file found"; \
	fi

# Check observer status
status:
	@if [ -f logs/observer.pid ]; then \
		pid=$$(cat logs/observer.pid); \
		if kill -0 $$pid 2>/dev/null; then \
			echo "Observer running (PID $$pid)"; \
		else \
			echo "Observer not running (stale PID file)"; \
		fi; \
	else \
		echo "Observer not running"; \
	fi

# Install all dependencies for autonomous agents
install-deps:
	@echo "Installing AgentGRIT dependencies..."
	@pip install playwright pytest-playwright requests aiogram
	@playwright install chromium
	@echo "✓ Dependencies installed"

# Start all services (API + Telegram + any registered agents) via the CLI entry point
run-agents: logs-dir
	@echo "Starting AgentGRIT services (python -m src.main)..."
	@$(PYTHON) -m src.main

# Stop a backgrounded run-agents-bg process
stop-agents:
	@echo "Stopping AgentGRIT services..."
	@pkill -f "src.main" || echo "No AgentGRIT services running"

# Run services in background (detached)
run-agents-bg: logs-dir
	@echo "Starting AgentGRIT services in background..."
	@nohup $(PYTHON) -m src.main > logs/agents.log 2>&1 &
	@echo "Services started. Check logs/agents.log for output."

# Deterministic daily debrief (schedulable). NOTIFY=1 sends via src.utils.notify.
debrief: logs-dir
	@if [ "$(NOTIFY)" = "1" ]; then \
		$(PYTHON) -m src.agents.daily_debrief_agent --notify; \
	else \
		$(PYTHON) -m src.agents.daily_debrief_agent; \
	fi

# Scaffold a governed project from an idea string
idea-project:
	@if [ -z "$(IDEA)" ]; then echo 'Usage: make idea-project IDEA="your idea"'; exit 1; fi
	@$(PYTHON) -m src.planning.idea_to_project "$(IDEA)"

# Propose local skills for a task (installs nothing)
skills-find:
	@if [ -z "$(TASK)" ]; then echo 'Usage: make skills-find TASK="format python"'; exit 1; fi
	@$(PYTHON) -m src.execution.skill_discovery "$(TASK)"

# Repo Steward — governed advisor (gardener + autonomy; no auto-edit)
agent-steward:
	@$(PYTHON) -m src.agents.repo_steward_agent "$(or $(DIR),.)"

# Legal research advisor — CourtListener public-record; cite-or-refuse; never files
agent-legal:
	@if [ -z "$(Q)" ]; then echo 'Usage: make agent-legal Q="case law research for counsel: <issue>"'; exit 1; fi
	@$(PYTHON) -m src.agents.legal_research_agent $(Q)

# GRIT Observe — keyless feeds → fuse → evidence gate (no action)
observe:
	@if [ -n "$(FEED)" ]; then \
		$(PYTHON) -m src.observe.run --feed "$(FEED)"; \
	else \
		$(PYTHON) -m src.observe.run; \
	fi

observe-fixture:
	@$(PYTHON) -m src.observe.run --fixture-dir tests/fixtures/observe

# Read-only operator console (renders logs; never acts). Start API first: make run-agents
console:
	@echo "AgentGRIT operator console (READ-ONLY)"
	@echo "  Open:  http://127.0.0.1:$${API_PORT:-8000}/console"
	@echo "  Data:  http://127.0.0.1:$${API_PORT:-8000}/console/data"
	@echo "  Start the API if needed:  python -m src.main --api-only"
	@echo "  This UI only GETs logs — it cannot spawn tasks or approve escalations."

# Domain governed-brief UI (read-only; verified citations only)
brief:
	@echo "AgentGRIT governed brief (READ-ONLY · domain user surface)"
	@echo "  Open:  http://127.0.0.1:$${API_PORT:-8000}/brief"
	@echo "  Data:  http://127.0.0.1:$${API_PORT:-8000}/brief/data?run=latest&profile=generic"
	@echo "  Legal profile sample:  .../brief/data?profile=legal"
	@echo "  Start the API if needed:  python -m src.main --api-only"
	@echo "  Agents write logs/briefs.jsonl; this UI only reads."

.PHONY: hud
hud:
	@$(PYTHON) scripts/dashboard.py

.PHONY: garden
garden:
	@$(PYTHON) scripts/gardener.py
