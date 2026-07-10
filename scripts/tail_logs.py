#!/usr/bin/env python3
"""
AgentGRIT Log Tail - Live Log Viewer

Watches logs/router.jsonl, logs/bylaws.jsonl, logs/heartbeat.jsonl
and displays entries in real-time with running counts.

Run: make tail
Stop: Ctrl+C

Usage:
  make tail                             # Watch all logs
  make tail ARGS=router                 # Watch only router (or run directly)
"""

import json
import signal
import sys
import time
from collections import defaultdict
from pathlib import Path

# Project root for log file paths
PROJECT_ROOT = Path(__file__).parent.parent

# Log files
LOG_FILES = {
    "router": PROJECT_ROOT / "logs" / "router.jsonl",
    "bylaws": PROJECT_ROOT / "logs" / "bylaws.jsonl",
    "heartbeat": PROJECT_ROOT / "logs" / "heartbeat.jsonl",
}

# Graceful shutdown
_shutdown = False


def _signal_handler(sig, frame):
    global _shutdown
    _shutdown = True
    print("\n")


# ANSI colors
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"

    @classmethod
    def disable(cls):
        """Disable colors for non-TTY output."""
        cls.RESET = ""
        cls.BOLD = ""
        cls.DIM = ""
        cls.RED = ""
        cls.GREEN = ""
        cls.YELLOW = ""
        cls.BLUE = ""
        cls.MAGENTA = ""
        cls.CYAN = ""


class LogStats:
    """Track running statistics."""

    def __init__(self):
        self.provider_counts = defaultdict(int)
        self.category_counts = defaultdict(int)
        self.action_counts = defaultdict(int)
        self.heartbeat_count = 0
        self.total_entries = 0

    def update_router(self, entry: dict):
        provider = entry.get("provider", "unknown")
        category = entry.get("category", "unknown")
        self.provider_counts[provider] += 1
        self.category_counts[category] += 1
        self.total_entries += 1

    def update_bylaws(self, entry: dict):
        action = entry.get("action", "unknown")
        self.action_counts[action] += 1
        self.total_entries += 1

    def update_heartbeat(self, entry: dict):
        self.heartbeat_count += 1
        # Also track nested router/bylaws if present
        if "router" in entry:
            provider = entry["router"].get("provider", "unknown")
            self.provider_counts[provider] += 1
        if "bylaws" in entry:
            action = entry["bylaws"].get("action", "unknown")
            self.action_counts[action] += 1
        self.total_entries += 1

    def summary_line(self) -> str:
        """One-line summary for status bar."""
        parts = []

        if self.provider_counts:
            providers = ", ".join(
                f"{k}:{v}" for k, v in sorted(self.provider_counts.items())
            )
            parts.append(f"providers[{providers}]")

        if self.action_counts:
            actions = ", ".join(
                f"{k}:{v}" for k, v in sorted(self.action_counts.items())
            )
            parts.append(f"actions[{actions}]")

        if self.heartbeat_count:
            parts.append(f"heartbeats:{self.heartbeat_count}")

        return " | ".join(parts) if parts else "no entries yet"


def format_router_entry(entry: dict) -> str:
    """Format a router log entry."""
    ts = entry.get("timestamp", "")[:19]
    provider = entry.get("provider", "?")
    category = entry.get("category", "?")
    confidence = entry.get("confidence", 0)
    caps = entry.get("required_capabilities", [])

    # Color by provider
    pcolor = {
        "ollama": Colors.GREEN,
        "perplexity": Colors.CYAN,
        "grok": Colors.YELLOW,
        "claude": Colors.MAGENTA,
    }.get(provider, Colors.RESET)

    caps_str = ",".join(caps) if caps else "-"

    return (
        f"{Colors.DIM}{ts}{Colors.RESET} "
        f"{Colors.BLUE}[router]{Colors.RESET} "
        f"{pcolor}{provider:<10}{Colors.RESET} "
        f"{category:<12} "
        f"conf={confidence:.1f} "
        f"caps=[{caps_str}]"
    )


def format_bylaws_entry(entry: dict) -> str:
    """Format a bylaws log entry."""
    ts = entry.get("timestamp", "")[:19]
    action = entry.get("action", "?")
    reason = entry.get("reason", "")[:50]
    role = entry.get("role", "?")

    # Color by action
    acolor = {
        "allow": Colors.GREEN,
        "block": Colors.RED,
        "warn": Colors.YELLOW,
        "audit": Colors.CYAN,
    }.get(action, Colors.RESET)

    return (
        f"{Colors.DIM}{ts}{Colors.RESET} "
        f"{Colors.YELLOW}[bylaws]{Colors.RESET} "
        f"{acolor}{action:<6}{Colors.RESET} "
        f"role={role:<10} "
        f"{reason}"
    )


def format_heartbeat_entry(entry: dict) -> str:
    """Format a heartbeat log entry."""
    ts = entry.get("timestamp", "")[:19]
    cycle = entry.get("cycle", 0)
    status = entry.get("status", "?")

    router_info = ""
    if "router" in entry:
        provider = entry["router"].get("provider", "?")
        router_info = f"router→{provider}"

    bylaws_info = ""
    if "bylaws" in entry:
        action = entry["bylaws"].get("action", "?")
        bylaws_info = f"bylaws→{action}"

    scolor = Colors.GREEN if status == "alive" else Colors.RED

    return (
        f"{Colors.DIM}{ts}{Colors.RESET} "
        f"{Colors.MAGENTA}[heartbeat]{Colors.RESET} "
        f"#{cycle:04d} "
        f"{scolor}{status}{Colors.RESET} "
        f"{router_info} {bylaws_info}"
    )


def tail_file(filepath: Path, last_pos: int) -> tuple[list[dict], int]:
    """Read new lines from file since last position."""
    entries = []

    if not filepath.exists():
        return entries, 0

    try:
        with open(filepath, "r") as f:
            f.seek(last_pos)
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            new_pos = f.tell()
    except Exception:
        return entries, last_pos

    return entries, new_pos


def print_stats_header(stats: LogStats):
    """Print stats header line."""
    print(
        f"{Colors.BOLD}Stats:{Colors.RESET} {stats.summary_line()}"
    )
    print("-" * 80)


def main():
    global _shutdown

    # Check for color support
    if not sys.stdout.isatty():
        Colors.disable()

    # Parse which logs to watch
    watch_logs = list(LOG_FILES.keys())
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in LOG_FILES:
            watch_logs = [arg]
        elif arg in ("--help", "-h"):
            print(__doc__)
            sys.exit(0)

    # Setup signal handler
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    print(f"{Colors.BOLD}AgentGRIT Log Tail{Colors.RESET}")
    print("=" * 40)
    print(f"Watching: {', '.join(watch_logs)}")
    print("Press Ctrl+C to stop")
    print("=" * 40)
    print()

    # Track file positions and stats
    positions = {name: 0 for name in watch_logs}
    stats = LogStats()

    # Start from end of existing files
    for name in watch_logs:
        filepath = LOG_FILES[name]
        if filepath.exists():
            positions[name] = filepath.stat().st_size

    formatters = {
        "router": format_router_entry,
        "bylaws": format_bylaws_entry,
        "heartbeat": format_heartbeat_entry,
    }

    stat_updaters = {
        "router": stats.update_router,
        "bylaws": stats.update_bylaws,
        "heartbeat": stats.update_heartbeat,
    }

    last_stats_time = 0

    try:
        while not _shutdown:
            new_entries = False

            for name in watch_logs:
                filepath = LOG_FILES[name]
                entries, new_pos = tail_file(filepath, positions[name])
                positions[name] = new_pos

                for entry in entries:
                    new_entries = True
                    stat_updaters[name](entry)
                    print(formatters[name](entry))

            # Print stats summary every 30 seconds if there's activity
            now = time.time()
            if stats.total_entries > 0 and now - last_stats_time > 30:
                print()
                print_stats_header(stats)
                last_stats_time = now

            time.sleep(0.5)

    finally:
        print()
        print(f"{Colors.BOLD}Final Stats:{Colors.RESET}")
        print(f"  Total entries: {stats.total_entries}")
        if stats.provider_counts:
            print(f"  Providers: {dict(stats.provider_counts)}")
        if stats.action_counts:
            print(f"  Actions: {dict(stats.action_counts)}")
        if stats.heartbeat_count:
            print(f"  Heartbeats: {stats.heartbeat_count}")


if __name__ == "__main__":
    main()
