"""
AgentGRIT Persistent Memory

Real, disk-backed memory for lessons learned during actual task execution -
closing a gap this project's own code admitted to: `AgentMemory` in
grit_agent.py is docstring-labeled "vector-searchable, persistent" but is
actually just an in-process list/dict that evaporates on process exit.
Verified directly: nothing in that class ever touches disk.

Design principles (deliberately narrower than a general-purpose agent
memory system - see each point for why):

1. Every write is bylaws-gated, not silent. A memory write goes through
   the SAME BylawEngine.evaluate() every other action in this codebase
   goes through, with action_type="memory_write". This is not
   decorative: the exact same BLOCKED_PATTERNS and security_sensitive
   ESCALATION_TRIGGERS that stop `cat .env` from running also stop a
   credential-shaped "fact" from ever reaching disk, for free, because
   of how the engine already works - no new regex list to write or let
   drift out of sync with the real one.

2. ESCALATE-level facts don't silently become live context. They land in
   a separate pending-review queue and are never folded into a future
   prompt until a human reviews them. An agent that can quietly rewrite
   its own future instructions without review is exactly the failure
   mode this project's bylaws/trust-ladder architecture exists to
   prevent - memory writes don't get an exemption from that.

3. Bounded and archived, never silently dropped. Oldest live entries move
   to a separate archive file when the cap is hit rather than being
   deleted, so nothing already-approved is ever lost - only pushed out
   of the "recent and relevant" set that gets rendered into prompts.

4. No new dependency, no vector DB. Recall is a plain keyword +
   task_pattern filter, consistent with this project's existing
   "smallest interface that works" instinct (see context_loader.py's own
   docstring for the same reasoning). Good enough to stop lessons from
   evaporating every process exit; not yet good enough to scale past a
   few hundred entries without smarter retrieval - a real limitation,
   noted rather than hidden.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bylaws import AgentRole, BylawAction, get_bylaw_engine

MAX_LIVE_ENTRIES = 60
MAX_FACT_CHARS = 400


@dataclass
class MemoryEntry:
    fact: str
    category: str = "technical_lesson"  # technical_lesson | project_fact | correction
    source_task: str = ""
    task_pattern: str | None = None
    evidence: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MemoryEntry":
        return cls(
            fact=d.get("fact", ""),
            category=d.get("category", "technical_lesson"),
            source_task=d.get("source_task", ""),
            task_pattern=d.get("task_pattern"),
            evidence=d.get("evidence"),
            created_at=d.get("created_at", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class MemoryWriteResult:
    written: bool
    bylaw_action: str
    reason: str
    entry: MemoryEntry | None = None


class MemoryStore:
    """
    Real, disk-backed lesson memory. Every write goes through the real
    bylaws engine before it touches disk - see module docstring point 1.
    """

    def __init__(
        self,
        live_path: str = "data/agent_memory.json",
        archive_path: str = "data/agent_memory_archive.json",
        pending_path: str = "data/agent_memory_pending.json",
        max_live_entries: int = MAX_LIVE_ENTRIES,
    ):
        self._live_path = live_path
        self._archive_path = archive_path
        self._pending_path = pending_path
        self._max_live_entries = max_live_entries
        self._live: list[MemoryEntry] = []
        self._pending: list[MemoryEntry] = []
        self._load()

    def _load(self) -> None:
        self._live = self._load_file(self._live_path)
        self._pending = self._load_file(self._pending_path)

    @staticmethod
    def _load_file(path: str) -> list[MemoryEntry]:
        p = Path(path)
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text())
        except Exception:
            return []
        return [MemoryEntry.from_dict(e) for e in data.get("entries", [])]

    @staticmethod
    def _save_file(path: str, entries: list[MemoryEntry]) -> None:
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            data = {"entries": [e.to_dict() for e in entries]}
            p.write_text(json.dumps(data, indent=2))
        except Exception:
            pass  # best-effort persistence, mirrors trust.py's own contract

    def _save(self) -> None:
        self._save_file(self._live_path, self._live)
        self._save_file(self._pending_path, self._pending)

    def _archive_oldest(self, count: int) -> None:
        if count <= 0:
            return
        to_archive, self._live = self._live[:count], self._live[count:]
        archived = self._load_file(self._archive_path)
        archived.extend(to_archive)
        self._save_file(self._archive_path, archived)

    def remember(
        self,
        fact: str,
        category: str = "technical_lesson",
        source_task: str = "",
        role: AgentRole = AgentRole.DEVELOPER,
        task_pattern: str | None = None,
        evidence: str | None = None,
    ) -> MemoryWriteResult:
        """
        The only way a fact reaches disk. Gated by the real bylaws engine
        - see module docstring point 1. Deliberately does NOT set a
        "filepath" key in context: this is not a source-code change, so
        the PR-requirement and verify-before-commit gates (which key off
        filepath in bylaws.py's evaluate()) correctly do not apply here;
        only Law 0 (BLOCKED_PATTERNS) and Law 2 (ESCALATION_TRIGGERS,
        including security_sensitive) run - exactly the protection this
        needs and nothing this doesn't.
        """
        fact = fact.strip()[:MAX_FACT_CHARS]
        if not fact:
            return MemoryWriteResult(written=False, bylaw_action="skip", reason="empty fact")

        engine = get_bylaw_engine(role)
        result = engine.evaluate(fact, context={}, action_type="memory_write")

        entry = MemoryEntry(
            fact=fact,
            category=category,
            source_task=source_task[:200],
            task_pattern=task_pattern,
            evidence=evidence,
        )

        if result.action == BylawAction.BLOCK:
            # Never written anywhere, not even pending - matches how
            # bylaws.py treats BLOCK everywhere else in this codebase.
            return MemoryWriteResult(
                written=False, bylaw_action=result.action.value, reason=result.reason
            )

        if result.action == BylawAction.ESCALATE:
            self._pending.append(entry)
            self._save()
            return MemoryWriteResult(
                written=False,
                bylaw_action=result.action.value,
                reason=result.reason,
                entry=entry,
            )

        # PROCEED / NOTIFY / VERIFY_FIRST all result in a live write.
        # Only BLOCK and ESCALATE actually stop something in this
        # codebase's bylaws model (see router.py's own handling of
        # NOTIFY - it proceeds and surfaces the notice, never blocks).
        self._live.append(entry)
        overflow = len(self._live) - self._max_live_entries
        if overflow > 0:
            self._archive_oldest(overflow)
        self._save()
        return MemoryWriteResult(
            written=True, bylaw_action=result.action.value, reason=result.reason, entry=entry
        )

    def recall(
        self, query: str = "", task_pattern: str | None = None, limit: int = 3
    ) -> list[MemoryEntry]:
        """
        Deliberately simple keyword + task_pattern filter - see module
        docstring point 4 on why this isn't a vector search.
        """
        query_words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2}
        scored: list[tuple[int, MemoryEntry]] = []
        for e in reversed(self._live):  # most recent first as a tiebreak
            score = 0
            if task_pattern and e.task_pattern == task_pattern:
                score += 2
            if query_words:
                fact_words = set(re.findall(r"[a-z0-9]+", e.fact.lower()))
                score += len(query_words & fact_words)
            if score > 0 or not query_words:
                scored.append((score, e))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [e for _, e in scored[:limit]]

    def pending_count(self) -> int:
        return len(self._pending)

    def live_count(self) -> int:
        return len(self._live)


_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    """Get or create the global memory store."""
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store


def render_memory_block(task: str, task_pattern: str | None = None, limit: int = 3) -> str:
    """
    Render up to `limit` relevant memories as a prompt-insertable block.
    Empty string if nothing relevant exists yet - callers should not add
    any wrapper text when this returns "".
    """
    store = get_memory_store()
    entries = store.recall(query=task, task_pattern=task_pattern, limit=limit)
    if not entries:
        return ""
    lines = "\n".join(
        f"- {e.fact} (learned from: {e.source_task[:80]})" for e in entries
    )
    return (
        "## Lessons from prior real runs (verify these still apply; "
        "do not treat as infallible)\n" + lines
    )


LESSON_LINE_RE = re.compile(r"^LESSON:\s*(.+)$", re.MULTILINE)


def extract_lesson(model_response: str) -> str | None:
    """
    Pull an optional self-reported LESSON line out of a model response,
    per the contract in identity.py's "Report format" section. Returns
    None if absent - most responses won't have one, and that is correct
    default behavior, not a failure to detect one.
    """
    match = LESSON_LINE_RE.search(model_response)
    if not match:
        return None
    lesson = match.group(1).strip()
    return lesson[:MAX_FACT_CHARS] if lesson else None
