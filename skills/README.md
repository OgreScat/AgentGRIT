# Skills directory

Drop-in skill modules for AgentGRIT's governed skill discovery
(`src/execution/skill_discovery.py`).

## Layout

```
skills/
  my-skill/
    SKILL.md          # required — name + description
  another.md          # or a single markdown file at the top level
```

### SKILL.md format

```markdown
# my-skill

Short description of what this skill does.

tags: lint, format, python
source: local
stars: 0
runs_code: false
permissions: filesystem
```

- First `# heading` is the skill name if not overridden.
- Body text is the description (used for task matching).
- Optional metadata lines (`tags:`, `source:`, `stars:`, `runs_code:`,
  `permissions:`) are parsed deterministically — no LLM.

## Discovery

```bash
# CLI (lists candidates; installs nothing)
PYTHONPATH=. python -m src.execution.skill_discovery "format python code"

# From code
from src.execution.skill_discovery import discover_local
candidates = discover_local("format python code")
```

Discovery is **propose-only**. Each candidate is reviewed by
`skill_review` (approve / review / reject). Nothing is installed without
a green-light path. Secret-touching or unvetted code skills always need
human confirm.

## Safety

- Default `runs_code: true` (conservative) when unspecified.
- Star counts are a weak prior, not proof — prefer explicit trusted sources.
- This directory is optional; an empty tree yields an empty catalog.
