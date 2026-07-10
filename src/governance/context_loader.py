"""AgentGRIT Project Context Loader

Scans a project's own anchor/doctrine docs and folds relevant context
into a task before dispatch, so a local model working on a project
actually knows that project's doctrine instead of operating blind.

Ships with zero projects configured on purpose -- add your own project
paths to PROJECT_PATHS below (or set them via your own settings fields
and wire them into _project_paths()). AgentGRIT does not pretend to
orchestrate a project it hasn't been told about: an unconfigured project
name returns "NO_PROJECT_CONTEXT_FOUND" so callers escalate instead of
guessing, per the Zeroth Law (governance/bylaws.py) -- a local model that
proceeds on zero context is exactly the failure mode this exists to
prevent.

This is a first pass, not a token-efficient semantic-retrieval system.
Anchor files are read directly and truncated per-file rather than
embedded/retrieved. Good enough to stop a local model from operating
with zero project context; not yet built for a large doctrine corpus.
"""

from __future__ import annotations

import re
from pathlib import Path

ANCHOR_PRIORITY = [
    "_START_HERE.md",
    "CLAUDE_CODE_BRIEF.md",
    "CLAUDE_CODE_LAUNCH.md",
    "CLAUDE.md",
    "AGENTS.md",
    "README.md",
]

# Secondary: doctrine-pattern files anywhere in the project (not just root).
# Pattern-match, don't hardcode one filename - real projects use different
# names for the same role (ARCHITECTURE.md, PRODUCT_DOCTRINE.md, etc).
DOCTRINE_PATTERN = re.compile(
    r"(DOCTRINE|ARCHITECTURE|GOVERNANCE|SPEC|STYLE|BIBLE|BRANDING|PLAN|METHOD)",
    re.IGNORECASE,
)

MAX_DOCTRINE_FILES = 3       # keep local-model context budget sane
MAX_CHARS_PER_FILE = 4000    # truncate long doctrine files rather than skip them
SKIP_DIR_NAMES = {"node_modules", ".git", "__pycache__", ".venv", "dist", "build"}

# Fill this in with your own project(s): {"your_project_key": Path("/path/to/it")}.
PROJECT_PATHS: dict[str, Path] = {
    # "your_project_key": Path("/path/to/your/project").expanduser(),
}


def _project_paths() -> dict[str, Path]:
    """Currently-configured project paths. Empty by default -- see PROJECT_PATHS above."""
    return PROJECT_PATHS


def detect_project(task: str) -> str | None:
    """
    Best-effort project detection from task text. Returns None if no
    known project is mentioned - callers should treat that as "no
    project context to load", not as an error. This is intentionally
    conservative: a false negative (missing an implicit project match)
    is safer than a false positive (loading the wrong project's doctrine
    into an unrelated task).
    """
    task_lower = task.lower()
    for name in _project_paths():
        if name in task_lower:
            return name
    return None


def load_project_context(project_name: str) -> str:
    """
    Scoped strictly to the named project's own folder - never reads
    outside it, and never reads any other configured project's folder
    even if both happen to be requested in the same session. Returns
    the literal string "NO_PROJECT_CONTEXT_FOUND" if the project isn't
    configured or has no anchor docs, so callers escalate instead of
    guessing (per this project's own founding discipline: a local model
    that proceeds on zero context is exactly the failure mode this
    exists to prevent).
    """
    paths = _project_paths()
    project_path = paths.get(project_name)

    if project_path is None or not project_path.is_dir():
        return "NO_PROJECT_CONTEXT_FOUND"

    anchors = []
    for name in ANCHOR_PRIORITY:
        candidate = project_path / name
        if candidate.is_file():
            anchors.append(candidate)

    doctrine_files: list[Path] = []
    try:
        for p in sorted(project_path.rglob("*.md")):
            if len(doctrine_files) >= MAX_DOCTRINE_FILES:
                break
            if p in anchors:
                continue
            if any(part in SKIP_DIR_NAMES for part in p.parts):
                continue
            if DOCTRINE_PATTERN.search(p.name):
                doctrine_files.append(p)
    except Exception:
        pass

    files_to_read = anchors + doctrine_files
    if not files_to_read:
        return "NO_PROJECT_CONTEXT_FOUND"

    parts = [f"# PROJECT CONTEXT: {project_name} ({project_path})"]
    for f in files_to_read:
        try:
            text = f.read_text(errors="replace")[:MAX_CHARS_PER_FILE]
            truncated_note = " [truncated]" if len(text) == MAX_CHARS_PER_FILE else ""
            parts.append(f"\n## {f.name}{truncated_note}\n{text}")
        except Exception as e:
            parts.append(f"\n## {f.name}\n[could not read: {e}]")

    return "\n".join(parts)
