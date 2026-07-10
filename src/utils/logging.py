"""
AgentGRIT Shared Logging Utilities

Centralized JSONL logging for observability.
Used by router, bylaws, and heartbeat systems.

Unit-testable: All functions accept optional log_dir parameter.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


# Default log directory (relative to project root)
DEFAULT_LOG_DIR = Path(__file__).parent.parent.parent / "logs"


def _rotate_if_needed(filepath: Path) -> None:
    """Roll a log file when it exceeds LOG_MAX_MB, keeping LOG_KEEP archives.

    router.jsonl -> router.jsonl.1 -> ... -> router.jsonl.<keep>, oldest dropped.
    Bounds machine-layer exhaust so no single log balloons -- paired with the
    gardener's large-file check (a rule with both a mechanism and a checker).
    """
    try:
        max_bytes = int(float(os.environ.get("LOG_MAX_MB", "5")) * 1024 * 1024)
        keep = int(os.environ.get("LOG_KEEP", "3"))
        if max_bytes <= 0 or not filepath.exists():
            return
        if filepath.stat().st_size <= max_bytes:
            return
        for i in range(keep - 1, 0, -1):
            src = filepath.parent / f"{filepath.name}.{i}"
            dst = filepath.parent / f"{filepath.name}.{i + 1}"
            if src.exists():
                src.replace(dst)
        filepath.replace(filepath.parent / f"{filepath.name}.1")
    except Exception:
        return


def write_jsonl(
    filename: str,
    entry: dict[str, Any],
    log_dir: Optional[Path] = None,
) -> bool:
    """
    Append a JSON entry to a JSONL log file.

    Args:
        filename: Name of the log file (e.g., "router.jsonl")
        entry: Dictionary to write as JSON line
        log_dir: Optional log directory (defaults to project logs/)

    Returns:
        True if write succeeded, False otherwise

    Example:
        write_jsonl("router.jsonl", {"provider": "ollama", "task": "..."})
    """
    log_dir = log_dir or DEFAULT_LOG_DIR

    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        filepath = log_dir / filename
        _rotate_if_needed(filepath)

        with open(filepath, "a") as f:
            f.write(json.dumps(entry) + "\n")

        return True
    except Exception:
        return False


def log_routing_decision(
    entry: dict[str, Any],
    log_dir: Optional[Path] = None,
) -> bool:
    """
    Log a routing decision to router.jsonl.

    Args:
        entry: Routing decision dict (provider, category, confidence, etc.)
        log_dir: Optional log directory for testing

    Returns:
        True if write succeeded
    """
    # Add timestamp if not present
    if "timestamp" not in entry:
        entry["timestamp"] = datetime.now().isoformat()

    return write_jsonl("router.jsonl", entry, log_dir)


def log_bylaw_decision(
    entry: dict[str, Any],
    log_dir: Optional[Path] = None,
) -> bool:
    """
    Log a bylaw decision to bylaws.jsonl.

    Args:
        entry: Bylaw decision dict (action, reason, rule, role, etc.)
        log_dir: Optional log directory for testing

    Returns:
        True if write succeeded
    """
    # Add timestamp if not present
    if "timestamp" not in entry:
        entry["timestamp"] = datetime.now().isoformat()

    return write_jsonl("bylaws.jsonl", entry, log_dir)


def log_heartbeat(
    entry: dict[str, Any],
    log_dir: Optional[Path] = None,
) -> bool:
    """
    Log a heartbeat entry to heartbeat.jsonl.

    Args:
        entry: Heartbeat dict (cycle, pid, status, router, bylaws, etc.)
        log_dir: Optional log directory for testing

    Returns:
        True if write succeeded
    """
    # Add timestamp if not present
    if "timestamp" not in entry:
        entry["timestamp"] = datetime.now().isoformat()

    return write_jsonl("heartbeat.jsonl", entry, log_dir)


def read_jsonl(
    filename: str,
    log_dir: Optional[Path] = None,
    limit: Optional[int] = None,
    offset: int = 0,
) -> list:
    """
    Read entries from a JSONL log file.

    Args:
        filename: Name of the log file
        log_dir: Optional log directory
        limit: Maximum entries to return (None = all)
        offset: Skip first N entries

    Returns:
        List of parsed JSON entries
    """
    log_dir = log_dir or DEFAULT_LOG_DIR
    filepath = log_dir / filename

    if not filepath.exists():
        return []

    entries = []
    try:
        with open(filepath, "r") as f:
            for i, line in enumerate(f):
                if i < offset:
                    continue
                if limit is not None and len(entries) >= limit:
                    break

                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except Exception:
        pass

    return entries


def count_jsonl(
    filename: str,
    log_dir: Optional[Path] = None,
) -> int:
    """
    Count entries in a JSONL log file.

    Args:
        filename: Name of the log file
        log_dir: Optional log directory

    Returns:
        Number of entries
    """
    log_dir = log_dir or DEFAULT_LOG_DIR
    filepath = log_dir / filename

    if not filepath.exists():
        return 0

    count = 0
    try:
        with open(filepath, "r") as f:
            for line in f:
                if line.strip():
                    count += 1
    except Exception:
        pass

    return count


def get_log_stats(
    log_dir: Optional[Path] = None,
) -> dict:
    """
    Get statistics for all log files.

    Returns:
        Dict with counts and last entry timestamps
    """
    log_dir = log_dir or DEFAULT_LOG_DIR

    stats = {}
    for filename in ["router.jsonl", "bylaws.jsonl", "heartbeat.jsonl"]:
        filepath = log_dir / filename
        name = filename.replace(".jsonl", "")

        if filepath.exists():
            entries = read_jsonl(filename, log_dir)
            stats[name] = {
                "count": len(entries),
                "last_entry": entries[-1] if entries else None,
            }
        else:
            stats[name] = {"count": 0, "last_entry": None}

    return stats
