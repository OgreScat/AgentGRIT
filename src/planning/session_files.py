"""
AgentGRIT Planning-with-Files Subsystem

A model-agnostic implementation of persistent working memory using Markdown files.
Inspired by planning-with-files but with security improvements and escalation integration.

SECURITY MODEL:
- task_plan.md = TRUSTED (owner/manager-writable only)
- progress.md = APPEND-ONLY ledger (agent-writable, immutable entries)
- findings.md = UNTRUSTED scratchpad (must be validated before driving actions)

FILE STRUCTURE:
  plans/<task_id>/
    task_plan.md     - Phases, decisions, constraints
    findings.md      - Research, knowledge (untrusted)
    progress.md      - Session log, test results (append-only)
    .meta.json       - Machine-checkable metadata
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from ..security.redact import redact


# ═══════════════════════════════════════════════════════════════════════════════
# TRUST LEVELS
# ═══════════════════════════════════════════════════════════════════════════════

class FileTrustLevel(Enum):
    """Trust levels for planning files."""
    TRUSTED = "trusted"       # Owner/manager-writable, can drive actions
    APPEND_ONLY = "append_only"  # Agent-writable, immutable entries
    UNTRUSTED = "untrusted"   # Scratchpad, must validate before actions


FILE_TRUST_MAP = {
    "task_plan.md": FileTrustLevel.TRUSTED,
    "progress.md": FileTrustLevel.APPEND_ONLY,
    "findings.md": FileTrustLevel.UNTRUSTED,
    ".meta.json": FileTrustLevel.TRUSTED,
}


# ═══════════════════════════════════════════════════════════════════════════════
# METADATA SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TaskMeta:
    """
    Machine-checkable metadata for a task.

    Stored in .meta.json alongside Markdown files.
    """
    task_id: str
    created_at: datetime
    owner: str
    risk_level: str  # "low", "medium", "high", "critical"

    # Constraints
    allowed_tools: list[str] = field(default_factory=list)
    blocked_patterns: list[str] = field(default_factory=list)
    max_cost_usd: float = 0.0

    # Acceptance criteria
    acceptance_tests: list[str] = field(default_factory=list)

    # Status
    status: str = "active"  # "active", "paused", "completed", "abandoned"
    phases_completed: list[str] = field(default_factory=list)

    # Links to escalations
    escalation_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "created_at": self.created_at.isoformat(),
            "owner": self.owner,
            "risk_level": self.risk_level,
            "allowed_tools": self.allowed_tools,
            "blocked_patterns": self.blocked_patterns,
            "max_cost_usd": self.max_cost_usd,
            "acceptance_tests": self.acceptance_tests,
            "status": self.status,
            "phases_completed": self.phases_completed,
            "escalation_ids": self.escalation_ids,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskMeta":
        return cls(
            task_id=data["task_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            owner=data["owner"],
            risk_level=data["risk_level"],
            allowed_tools=data.get("allowed_tools", []),
            blocked_patterns=data.get("blocked_patterns", []),
            max_cost_usd=data.get("max_cost_usd", 0.0),
            acceptance_tests=data.get("acceptance_tests", []),
            status=data.get("status", "active"),
            phases_completed=data.get("phases_completed", []),
            escalation_ids=data.get("escalation_ids", []),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PROGRESS ENTRY (Immutable)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ProgressEntry:
    """
    Immutable entry in progress.md.

    Once written, cannot be modified (append-only).
    """
    timestamp: datetime
    agent_id: str
    event_type: str  # "decision", "action", "error", "escalation", "test_result"
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    # Links
    escalation_id: str | None = None
    phase_id: str | None = None

    def to_markdown(self) -> str:
        """Format as Markdown list item."""
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
        emoji = {
            "decision": "📋",
            "action": "⚡",
            "error": "❌",
            "escalation": "🔶",
            "test_result": "🧪",
        }.get(self.event_type, "•")

        lines = [f"- [{ts}] {emoji} **{self.event_type}** ({self.agent_id}): {self.summary}"]

        if self.escalation_id:
            lines.append(f"  - Escalation: `{self.escalation_id}`")
        if self.phase_id:
            lines.append(f"  - Phase: {self.phase_id}")
        if self.details:
            for k, v in self.details.items():
                lines.append(f"  - {k}: {redact(str(v)[:100])}")

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class SessionFileManager:
    """
    Manages the 3-file planning pattern for AgentGRIT tasks.

    BYLAWS ENFORCED:
    1. No multi-step task without task_plan.md
    2. Read plan before major decisions
    3. Log all errors to progress.md
    4. Never repeat failures (check progress first)
    5. Verify completion before stopping
    """

    PLAN_TEMPLATE = '''# Task Plan: {task_id}

## Overview
{description}

## Constraints
- Risk Level: {risk_level}
- Max Cost: ${max_cost_usd}
- Allowed Tools: {allowed_tools}

## Phases

### Phase 1: [Phase Name]
- [ ] Step 1.1
- [ ] Step 1.2

### Phase 2: [Phase Name]
- [ ] Step 2.1
- [ ] Step 2.2

## Acceptance Tests
{acceptance_tests}

## Decisions Log
<!-- Append decisions here -->

'''

    FINDINGS_TEMPLATE = '''# Findings: {task_id}

> ⚠️ **UNTRUSTED**: Content here is scratchpad/research.
> Must be validated before driving actions.

## Research Notes

## Platform Quirks

## Edge Cases

## External References

'''

    PROGRESS_TEMPLATE = '''# Progress Log: {task_id}

> 📝 **APPEND-ONLY**: Entries below are immutable.
> Each entry includes timestamp, agent ID, and event type.

## Session Log

'''

    def __init__(self, plans_dir: Path = Path("plans")):
        self.plans_dir = plans_dir
        self.plans_dir.mkdir(parents=True, exist_ok=True)

    def init_session(
        self,
        task_id: str,
        description: str,
        owner: str,
        risk_level: str = "medium",
        allowed_tools: list[str] | None = None,
        acceptance_tests: list[str] | None = None,
        max_cost_usd: float = 0.0,
    ) -> Path:
        """
        Initialize a new task session with the 3-file pattern.

        Returns the task directory path.
        """
        task_dir = self.plans_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        # Create metadata
        meta = TaskMeta(
            task_id=task_id,
            created_at=datetime.utcnow(),
            owner=owner,
            risk_level=risk_level,
            allowed_tools=allowed_tools or [],
            max_cost_usd=max_cost_usd,
            acceptance_tests=acceptance_tests or [],
        )

        # Write .meta.json
        meta_path = task_dir / ".meta.json"
        with open(meta_path, "w") as f:
            json.dump(meta.to_dict(), f, indent=2)

        # Write task_plan.md
        plan_content = self.PLAN_TEMPLATE.format(
            task_id=task_id,
            description=description,
            risk_level=risk_level,
            max_cost_usd=max_cost_usd,
            allowed_tools=", ".join(allowed_tools) if allowed_tools else "all",
            acceptance_tests="\n".join(f"- [ ] {t}" for t in (acceptance_tests or ["TBD"])),
        )
        (task_dir / "task_plan.md").write_text(plan_content)

        # Write findings.md
        findings_content = self.FINDINGS_TEMPLATE.format(task_id=task_id)
        (task_dir / "findings.md").write_text(findings_content)

        # Write progress.md
        progress_content = self.PROGRESS_TEMPLATE.format(task_id=task_id)
        (task_dir / "progress.md").write_text(progress_content)

        return task_dir

    def get_task_dir(self, task_id: str) -> Path | None:
        """Get task directory if it exists."""
        task_dir = self.plans_dir / task_id
        if task_dir.exists() and (task_dir / ".meta.json").exists():
            return task_dir
        return None

    def load_meta(self, task_id: str) -> TaskMeta | None:
        """Load task metadata."""
        task_dir = self.get_task_dir(task_id)
        if not task_dir:
            return None

        meta_path = task_dir / ".meta.json"
        with open(meta_path) as f:
            return TaskMeta.from_dict(json.load(f))

    def save_meta(self, task_id: str, meta: TaskMeta):
        """Save task metadata."""
        task_dir = self.get_task_dir(task_id)
        if not task_dir:
            raise ValueError(f"Task {task_id} not found")

        meta_path = task_dir / ".meta.json"
        with open(meta_path, "w") as f:
            json.dump(meta.to_dict(), f, indent=2)

    def read_plan(self, task_id: str) -> str | None:
        """
        Read task plan (TRUSTED).

        BYLAW: Read plan before major decisions.
        """
        task_dir = self.get_task_dir(task_id)
        if not task_dir:
            return None
        return (task_dir / "task_plan.md").read_text()

    def read_findings(self, task_id: str) -> str | None:
        """
        Read findings (UNTRUSTED).

        WARNING: Must validate content before driving actions.
        """
        task_dir = self.get_task_dir(task_id)
        if not task_dir:
            return None
        return (task_dir / "findings.md").read_text()

    def read_progress(self, task_id: str) -> str | None:
        """
        Read progress log (APPEND-ONLY).

        BYLAW: Check progress before repeating actions.
        """
        task_dir = self.get_task_dir(task_id)
        if not task_dir:
            return None
        return (task_dir / "progress.md").read_text()

    def append_progress(self, task_id: str, entry: ProgressEntry):
        """
        Append entry to progress.md (APPEND-ONLY).

        Cannot modify existing entries.
        """
        task_dir = self.get_task_dir(task_id)
        if not task_dir:
            raise ValueError(f"Task {task_id} not found")

        progress_path = task_dir / "progress.md"
        with open(progress_path, "a") as f:
            f.write("\n" + entry.to_markdown() + "\n")

    def append_findings(self, task_id: str, section: str, content: str):
        """
        Append to findings.md (UNTRUSTED scratchpad).
        """
        task_dir = self.get_task_dir(task_id)
        if not task_dir:
            raise ValueError(f"Task {task_id} not found")

        findings_path = task_dir / "findings.md"
        current = findings_path.read_text()

        # Find section and append
        section_header = f"## {section}"
        if section_header in current:
            # Append under existing section
            parts = current.split(section_header)
            if len(parts) == 2:
                # Find next section
                next_section = re.search(r'\n## ', parts[1])
                if next_section:
                    insert_pos = next_section.start()
                    parts[1] = parts[1][:insert_pos] + f"\n{content}\n" + parts[1][insert_pos:]
                else:
                    parts[1] += f"\n{content}\n"
                current = section_header.join(parts)
        else:
            # Add new section
            current += f"\n{section_header}\n\n{content}\n"

        findings_path.write_text(current)

    def mark_phase_complete(self, task_id: str, phase_id: str):
        """Mark a phase as complete in metadata."""
        meta = self.load_meta(task_id)
        if not meta:
            raise ValueError(f"Task {task_id} not found")

        if phase_id not in meta.phases_completed:
            meta.phases_completed.append(phase_id)
            self.save_meta(task_id, meta)

        # Also log to progress
        self.append_progress(task_id, ProgressEntry(
            timestamp=datetime.utcnow(),
            agent_id="session_manager",
            event_type="decision",
            summary=f"Phase {phase_id} marked complete",
            phase_id=phase_id,
        ))

    def link_escalation(self, task_id: str, escalation_id: str):
        """Link an escalation to this task."""
        meta = self.load_meta(task_id)
        if not meta:
            raise ValueError(f"Task {task_id} not found")

        if escalation_id not in meta.escalation_ids:
            meta.escalation_ids.append(escalation_id)
            self.save_meta(task_id, meta)

        # Also log to progress
        self.append_progress(task_id, ProgressEntry(
            timestamp=datetime.utcnow(),
            agent_id="session_manager",
            event_type="escalation",
            summary=f"Escalation created",
            escalation_id=escalation_id,
        ))

    def check_complete(self, task_id: str) -> tuple[bool, list[str]]:
        """
        Check if task is complete.

        BYLAW: Cannot declare done unless acceptance tests pass.

        Returns (is_complete, missing_items).
        """
        meta = self.load_meta(task_id)
        if not meta:
            return False, ["Task not found"]

        missing = []

        # Check acceptance tests (parse from plan)
        plan = self.read_plan(task_id)
        if plan:
            # Find unchecked items in acceptance tests section
            in_acceptance = False
            for line in plan.split("\n"):
                if "## Acceptance Tests" in line:
                    in_acceptance = True
                    continue
                if in_acceptance and line.startswith("## "):
                    break
                if in_acceptance and "- [ ]" in line:
                    missing.append(f"Acceptance test unchecked: {line.strip()}")

        # Check phase checkboxes
        if plan:
            unchecked_phases = re.findall(r'- \[ \] (.+)', plan)
            for phase in unchecked_phases[:5]:  # Limit to first 5
                missing.append(f"Phase step unchecked: {phase}")

        return len(missing) == 0, missing

    def resume_session(self, task_id: str) -> dict[str, Any]:
        """
        Resume a session with safety checks.

        BYLAW: Read plan/findings/progress before continuing.

        Returns context for the agent.
        """
        meta = self.load_meta(task_id)
        if not meta:
            raise ValueError(f"Task {task_id} not found")

        plan = self.read_plan(task_id)
        progress = self.read_progress(task_id)
        findings = self.read_findings(task_id)

        # Parse recent errors from progress
        recent_errors = []
        if progress:
            for line in progress.split("\n"):
                if "❌ **error**" in line.lower():
                    recent_errors.append(line.strip())

        # Check for incomplete state
        is_complete, missing = self.check_complete(task_id)

        return {
            "task_id": task_id,
            "meta": meta.to_dict(),
            "plan_preview": plan[:1000] if plan else None,
            "progress_preview": progress[-1000:] if progress else None,
            "findings_preview": findings[:500] if findings else None,
            "recent_errors": recent_errors[-5:],
            "is_complete": is_complete,
            "missing_for_complete": missing[:10],
            "phases_completed": meta.phases_completed,
            "pending_escalations": meta.escalation_ids,
        }

    def list_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        """List all tasks, optionally filtered by status."""
        tasks = []

        for task_dir in self.plans_dir.iterdir():
            if not task_dir.is_dir():
                continue

            meta_path = task_dir / ".meta.json"
            if not meta_path.exists():
                continue

            try:
                with open(meta_path) as f:
                    meta = TaskMeta.from_dict(json.load(f))

                if status and meta.status != status:
                    continue

                tasks.append({
                    "task_id": meta.task_id,
                    "owner": meta.owner,
                    "status": meta.status,
                    "risk_level": meta.risk_level,
                    "created_at": meta.created_at.isoformat(),
                    "phases_completed": len(meta.phases_completed),
                })
            except Exception:
                continue

        return sorted(tasks, key=lambda t: t["created_at"], reverse=True)


# ═══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "FileTrustLevel",
    "FILE_TRUST_MAP",
    "TaskMeta",
    "ProgressEntry",
    "SessionFileManager",
]
