#!/usr/bin/env python3
"""
AgentGRIT Observer - Continuous Heartbeat Loop

Runs until Ctrl+C, performing periodic:
- Trivial routed task (exercises router without external calls)
- Bylaw check (exercises bylaws)
- Heartbeat logging

Run: make run
Stop: Ctrl+C or make stop

Offline-safe: No API keys or network calls required.
"""

import json
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

# Project root for PID file and logs
PROJECT_ROOT = Path(__file__).parent.parent

# Graceful shutdown flag
_shutdown = False


def _signal_handler(sig, frame):
    """Handle Ctrl+C gracefully."""
    global _shutdown
    _shutdown = True
    print("\n\nShutting down observer...")


try:
    from src.utils.logging import log_heartbeat
except ImportError as e:
    print(f"Import error: {e}")
    print("\nRun via Makefile (sets PYTHONPATH correctly):")
    print("  make run")
    sys.exit(1)


def write_pid_file():
    """Write PID file for make stop."""
    pid_file = PROJECT_ROOT / "logs" / "observer.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))
    return pid_file


def remove_pid_file():
    """Remove PID file on shutdown."""
    pid_file = PROJECT_ROOT / "logs" / "observer.pid"
    if pid_file.exists():
        pid_file.unlink()


def run_heartbeat_cycle(cycle_num: int):
    """
    Run one heartbeat cycle:
    1. Route a trivial task (no external calls)
    2. Check a bylaw
    3. Log heartbeat
    """
    from src.execution.router import LLMRouter
    from src.governance.bylaws import get_observer_engine

    timestamp = datetime.now().isoformat()

    # 1. Trivial routed task (classification only, no execution)
    router = LLMRouter()
    trivial_tasks = [
        "Format this code nicely",
        "Explain what a variable is",
        "Add comments to this function",
        "Rename this variable",
        "What does this line do?",
    ]
    task = trivial_tasks[cycle_num % len(trivial_tasks)]
    decision = router.route_with_evidence(task)

    # 2. Bylaw check (observer role)
    engine = get_observer_engine()
    bylaw_commands = [
        "echo hello",
        "ls -la",
        "cat file.txt",
        "rm -rf /",
        "git status",
    ]
    command = bylaw_commands[cycle_num % len(bylaw_commands)]
    bylaw_result = engine.evaluate(command, action_type="bash")

    # 3. Log heartbeat
    heartbeat_entry = {
        "timestamp": timestamp,
        "cycle": cycle_num,
        "pid": os.getpid(),
        "router": {
            "task": task,
            "provider": decision.provider,
            "category": decision.category.value,
        },
        "bylaws": {
            "command": command,
            "action": bylaw_result.action.value,
        },
        "status": "alive",
    }
    log_heartbeat(heartbeat_entry)

    return decision, bylaw_result


def main():
    """Main observer loop."""
    global _shutdown

    # Parse interval from args or env
    interval = int(os.environ.get("OBSERVER_INTERVAL", "30"))
    if len(sys.argv) > 1:
        try:
            interval = int(sys.argv[1])
        except ValueError:
            pass

    # Import check (already done at top of file, but verify modules loaded)
    from src.execution.router import LLMRouter
    from src.governance.bylaws import get_observer_engine

    # Setup signal handler
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Write PID file
    pid_file = write_pid_file()

    print("AgentGRIT Observer")
    print("=" * 40)
    print(f"PID: {os.getpid()}")
    print(f"Interval: {interval}s")
    print(f"Logs: logs/heartbeat.jsonl")
    print(f"Stop: Ctrl+C or 'make stop'")
    print("=" * 40)
    print()

    cycle = 0
    try:
        while not _shutdown:
            cycle += 1
            timestamp = datetime.now().strftime("%H:%M:%S")

            try:
                decision, bylaw_result = run_heartbeat_cycle(cycle)
                print(
                    f"[{timestamp}] #{cycle:04d} | "
                    f"router → {decision.provider:<10} | "
                    f"bylaws → {bylaw_result.action.value}"
                )
            except Exception as e:
                print(f"[{timestamp}] #{cycle:04d} | ERROR: {e}")

            # Sleep in small increments for responsive shutdown
            for _ in range(interval):
                if _shutdown:
                    break
                time.sleep(1)

    finally:
        remove_pid_file()
        print(f"\nObserver stopped after {cycle} cycles.")
        print(f"Logs: logs/heartbeat.jsonl")


if __name__ == "__main__":
    main()
