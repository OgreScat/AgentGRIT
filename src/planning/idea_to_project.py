"""
Idea → project scaffold -- offline, deterministic.

Given a free-text idea, create a governed project skeleton under projects/:

  projects/<slug>/
    _START_HERE.md      -- purpose, constraints, next steps
    MEMORY.md           -- append-only session memory (empty starter)
    RESEARCH_PLAN.md    -- research questions + optional skill candidates

Uses existing conventions from context_loader (ANCHOR_PRIORITY includes
_START_HERE.md) so load_project_context can pick the project up once
registered in PROJECT_PATHS.

No network required. Optional skill_discovery.discover_local for related
skills (reads local skills/ only).

CLI:
  python -m src.planning.idea_to_project "build a cost-aware changelog bot"
  python -m src.planning.idea_to_project "..." --root /tmp/projects
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PROJECTS = _REPO_ROOT / "projects"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(idea: str, max_len: int = 48) -> str:
    s = (idea or "").strip().lower()
    s = _SLUG_RE.sub("-", s).strip("-")
    if not s:
        s = "untitled-idea"
    return s[:max_len].rstrip("-")


@dataclass
class ScaffoldResult:
    path: Path
    slug: str
    files: list[str]
    skill_candidates: list[str]

    def to_entry(self) -> dict:
        return {
            "path": str(self.path),
            "slug": self.slug,
            "files": list(self.files),
            "skill_candidates": list(self.skill_candidates),
        }


def _start_here(idea: str, slug: str) -> str:
    today = date.today().isoformat()
    return f"""# {slug}

Created: {today}

## Idea

{idea.strip()}

## Purpose

Governed workspace for this idea. Fill in success criteria before any agent
is allowed to act on it unattended.

## Constraints

- Dry-run first; no production deploys or money movement from this scaffold.
- Route work through AgentGRIT bylaws + autonomy gates.
- Evidence before "done" (tests, diffs, logs).

## Next steps

1. Write acceptance criteria in this file.
2. Flesh out RESEARCH_PLAN.md (what must be true before building).
3. Register the path in `src/governance/context_loader.PROJECT_PATHS` if you
   want local models to load this doctrine automatically:
   `"{slug}": Path("projects/{slug}")`
4. Run a debrief after the first real session: `make debrief`

## Status

scaffold — not production
"""


def _memory_starter(slug: str) -> str:
    today = date.today().isoformat()
    return f"""# MEMORY — {slug}

Append-only. Newest entries at the top. Short facts only.

## {today}

- Scaffold created from idea_to_project. No outcomes yet.
"""


def _research_plan(idea: str, skill_lines: list[str]) -> str:
    skills_block = (
        "\n".join(f"- {s}" for s in skill_lines)
        if skill_lines
        else "- (no local skill candidates matched — add skills under skills/)"
    )
    return f"""# Research plan

## Question

What must we know before building: {idea.strip()}

## Free-first research

1. Local docs / prior MEMORY.md entries
2. Keyless web (DuckDuckGo) via `src.execution.research`
3. Paid providers only if free evidence is insufficient (culminate)

## Open unknowns

- [ ] Scope boundaries (what is out of scope)
- [ ] Success metrics
- [ ] Failure modes and rollback

## Related local skills (propose-only)

{skills_block}
"""


def scaffold_idea(
    idea: str,
    *,
    root: Path | None = None,
    slug: str | None = None,
    include_skills: bool = True,
) -> ScaffoldResult:
    """Create project skeleton. Idempotent for missing files only (won't overwrite)."""
    if not (idea or "").strip():
        raise ValueError("idea must be non-empty")
    base = Path(root) if root is not None else _DEFAULT_PROJECTS
    use_slug = slug or slugify(idea)
    dest = base / use_slug
    dest.mkdir(parents=True, exist_ok=True)

    skill_candidates: list[str] = []
    if include_skills:
        try:
            from src.execution.skill_discovery import discover_local
            for c in discover_local(idea, top=5):
                skill_candidates.append(
                    f"{c.skill.name} [{c.pass_name}] score={c.score} → {c.decision}"
                )
        except Exception:
            pass

    files_written: list[str] = []
    plan = {
        "_START_HERE.md": _start_here(idea, use_slug),
        "MEMORY.md": _memory_starter(use_slug),
        "RESEARCH_PLAN.md": _research_plan(idea, skill_candidates),
    }
    for name, content in plan.items():
        path = dest / name
        if path.exists():
            continue
        path.write_text(content, encoding="utf-8")
        files_written.append(name)

    return ScaffoldResult(
        path=dest,
        slug=use_slug,
        files=files_written,
        skill_candidates=skill_candidates,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scaffold a governed project from an idea")
    parser.add_argument("idea", nargs="+", help="Idea text")
    parser.add_argument("--root", type=Path, default=None, help="Projects root (default: ./projects)")
    parser.add_argument("--slug", default=None, help="Override directory slug")
    parser.add_argument("--no-skills", action="store_true", help="Skip local skill discovery")
    args = parser.parse_args(argv)
    idea = " ".join(args.idea)
    result = scaffold_idea(
        idea,
        root=args.root,
        slug=args.slug,
        include_skills=not args.no_skills,
    )
    print(f"project: {result.path}")
    print(f"slug:    {result.slug}")
    print(f"files:   {', '.join(result.files) or '(all already present)'}")
    if result.skill_candidates:
        print("skills:")
        for s in result.skill_candidates:
            print(f"  - {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
