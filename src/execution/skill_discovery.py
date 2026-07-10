"""Governed skill-discovery -- JR finds, GRIT reviews, GM green-lights.

Your doctrine: build off things even if only *remotely* related, but stay governed AND
stay automated -- the human should rarely be in the loop. So discovery runs three ranked
passes to FIND candidates, then each is run through the in-house merit review
(`skill_review`) so the GM can green-light the clearly-good and reject the clearly-bad on
its own authority. Only the consequential residue (secret access, unvetted code, or a
high-stakes context) reaches you.

  1. direct        -- a skill that does exactly the task (name/description overlap)
  2. adjacent      -- solves the *shape* of the problem in a neighbouring domain
  3. recombination -- two partial skills that COMPOSE to cover the task

Works over a catalog you supply (a registry query, a local skills dir), so it is offline-
testable and provider-agnostic. It PROPOSES; nothing is installed without the verdict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from src.execution.skill_review import Decision, SkillVerdict, review

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "to", "of", "for", "and", "or", "in", "on", "with",
         "my", "your", "that", "this", "it", "from", "into"}

TRUSTED_SOURCES: tuple[str, ...] = ()
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SKILLS_DIR = _REPO_ROOT / "skills"


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower())
            if w not in _STOP and len(w) > 2}


@dataclass
class Skill:
    name: str
    description: str = ""
    source: str = ""            # e.g. "github:owner/repo"
    stars: int = 0
    tags: tuple[str, ...] = ()
    runs_code: bool = True       # conservative default: assume it can execute
    permissions: tuple[str, ...] = ()   # e.g. ("network",) or ("secrets","filesystem")


@dataclass
class Candidate:
    skill: Skill
    pass_name: str               # direct | adjacent | recombination
    score: float
    vetted: bool
    vet_reason: str
    decision: str                # approve | review | reject
    auto_greenlight: bool
    requires_human_confirm: bool
    reasons: list = field(default_factory=list)


def vet(skill: Skill, min_stars: int = 50,
        trusted: tuple[str, ...] = TRUSTED_SOURCES) -> tuple[bool, str]:
    """Reputation gate: trusted source OR enough stars. Never auto-trusts the unknown.

    NOTE: star-count is a WEAK signal (stars are buyable). Real trust requires
    populating TRUSTED_SOURCES with an explicit allowlist of vetted publishers;
    treat stars only as a soft prior, not proof."""
    src = (skill.source or "").lower()
    if any(src.startswith(t.lower()) for t in trusted):
        return True, "trusted source"
    if skill.stars >= min_stars:
        return True, f"{skill.stars} stars >= {min_stars}"
    return False, f"unvetted: {skill.stars} stars < {min_stars}, source not trusted"


def _score(task_tokens: set[str], text_tokens: set[str]) -> float:
    if not task_tokens:
        return 0.0
    return round(len(task_tokens & text_tokens) / len(task_tokens), 4)


def _candidate(sk: Skill, pass_name: str, score: float, *, min_stars: int,
               trusted: tuple[str, ...], high_stakes: bool) -> Candidate:
    ok, why = vet(sk, min_stars, trusted)
    verdict: SkillVerdict = review(sk, score, vetted=ok, high_stakes=high_stakes)
    return Candidate(sk, pass_name, score, ok, why, verdict.decision.value,
                     verdict.auto_greenlight, verdict.requires_human, verdict.reasons)


def discover(task: str, catalog: list[Skill], *, min_stars: int = 50,
             trusted: tuple[str, ...] = TRUSTED_SOURCES, top: int = 5,
             direct_threshold: float = 0.34, high_stakes: bool = False) -> list[Candidate]:
    """Find + review candidates for `task`. The GM green-lights within its ceiling; only
    the consequential residue is left `requires_human_confirm`."""
    tt = _tokens(task)
    cands: list[Candidate] = []
    for sk in catalog:
        direct = _score(tt, _tokens(f"{sk.name} {sk.description}"))
        adjacent = _score(tt, _tokens(" ".join(sk.tags)))
        if direct >= direct_threshold:
            pass_name, sc = "direct", direct
        elif adjacent > 0:
            pass_name, sc = "adjacent", round(adjacent * 0.7, 4)
        else:
            continue
        cands.append(_candidate(sk, pass_name, sc, min_stars=min_stars,
                                trusted=trusted, high_stakes=high_stakes))

    cands.sort(key=lambda c: c.score, reverse=True)

    # recombination: if nothing matched directly, propose the top two as a composition
    if cands and cands[0].pass_name != "direct" and len(cands) >= 2:
        a, b = cands[0], cands[1]
        combo_skill = Skill(
            name=f"{a.skill.name} + {b.skill.name}", description="composed capability",
            source="composition", stars=min(a.skill.stars, b.skill.stars),
            runs_code=(a.skill.runs_code or b.skill.runs_code),
            permissions=tuple(set(a.skill.permissions) | set(b.skill.permissions)))
        combo_score = round(min(1.0, a.score + b.score), 4)
        # a composition is vetted only if both parts were
        combo = _candidate(combo_skill, "recombination", combo_score,
                           min_stars=min_stars, trusted=trusted, high_stakes=high_stakes)
        combo.vetted = a.vetted and b.vetted
        cands.append(combo)

    return cands[:top]


def default_skills_dir() -> Path:
    return _DEFAULT_SKILLS_DIR


def _parse_skill_md(path: Path) -> Skill | None:
    """Parse a SKILL.md (or top-level .md) into a Skill. Fail-soft → None."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    name = path.parent.name if path.name.upper() == "SKILL.MD" else path.stem
    description_lines: list[str] = []
    tags: list[str] = []
    source = f"local:{path.parent.name if path.name.upper() == 'SKILL.MD' else path.stem}"
    stars = 0
    runs_code = True
    permissions: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                name = heading
            continue
        low = stripped.lower()
        if low.startswith("tags:"):
            tags = [t.strip() for t in stripped.split(":", 1)[1].split(",") if t.strip()]
        elif low.startswith("source:"):
            source = stripped.split(":", 1)[1].strip() or source
        elif low.startswith("stars:"):
            try:
                stars = int(stripped.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif low.startswith("runs_code:"):
            runs_code = stripped.split(":", 1)[1].strip().lower() in ("true", "1", "yes")
        elif low.startswith("permissions:"):
            permissions = [p.strip() for p in stripped.split(":", 1)[1].split(",") if p.strip()]
        elif stripped:
            description_lines.append(stripped)

    desc = " ".join(description_lines).strip()
    if not name:
        return None
    return Skill(
        name=name,
        description=desc,
        source=source,
        stars=stars,
        tags=tuple(tags),
        runs_code=runs_code,
        permissions=tuple(permissions),
    )


def load_catalog_from_dir(skills_dir: Path | None = None) -> list[Skill]:
    """Load skills from a drop-in directory (see skills/README.md)."""
    root = skills_dir or default_skills_dir()
    if not root.is_dir():
        return []
    skills: list[Skill] = []
    seen: set[str] = set()
    for skill_md in sorted(root.glob("*/SKILL.md")):
        sk = _parse_skill_md(skill_md)
        if sk and sk.name not in seen:
            skills.append(sk)
            seen.add(sk.name)
    for md in sorted(root.glob("*.md")):
        if md.name.upper() == "README.MD":
            continue
        sk = _parse_skill_md(md)
        if sk and sk.name not in seen:
            skills.append(sk)
            seen.add(sk.name)
    return skills


def discover_local(
    task: str,
    skills_dir: Path | None = None,
    **kwargs,
) -> list[Candidate]:
    """Discover against the repo skills/ catalog (or an explicit dir). Live entry."""
    catalog = load_catalog_from_dir(skills_dir)
    return discover(task, catalog, **kwargs)


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "format python code"
    hits = discover_local(q)
    print(f"task: {q}")
    print(f"catalog size: {len(load_catalog_from_dir())}")
    if not hits:
        print("no candidates")
    for c in hits:
        print(
            f"  [{c.pass_name}] {c.skill.name} score={c.score} "
            f"decision={c.decision} human={c.requires_human_confirm}"
        )
