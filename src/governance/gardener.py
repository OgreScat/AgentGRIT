"""The GRIT gardener -- nightly mechanical checkers that keep the memory layer honest.

Premise, learned from knowledge bases that rot: a rule without a checker does not
exist. Doctrine says "keep the environment map current", "no secrets in docs", "every
memory anchor is present" -- this module turns each of those into a DETERMINISTIC check
that runs on a schedule and REPORTS drift instead of letting it accumulate. No LLM in
the loop: every finding is reproducible from the filesystem.

A vault has two layers, treated differently:
  - knowledge layer : durable doctrine / notes (MEMORY.md, JOBS.md, docs/, the charter)
                      -- must stay consistent; never auto-pruned.
  - machine layer   : agent exhaust (logs/*.jsonl, *.db, caches) -- fine to be noisy,
                      but must NOT be tracked in git or bloat the tree.

Findings are severity-graded so the GM can honor the autonomy threshold: INFO / LOW /
MEDIUM are logged (safe auto-fixes may be applied by the caller); HIGH is a Zeroth-Law
escalation (a leaked secret, a doctrine map that no longer matches reality).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import IntEnum
from pathlib import Path


class Severity(IntEnum):
    INFO = 10
    LOW = 20
    MEDIUM = 30
    HIGH = 40

    @property
    def label(self) -> str:
        return self.name


@dataclass
class Finding:
    checker: str
    severity: Severity
    path: str
    detail: str

    def as_dict(self) -> dict:
        return {"checker": self.checker, "severity": self.severity.label,
                "path": self.path, "detail": self.detail}


# --- config defaults --------------------------------------------------------

# Machine-layer dirs: agent exhaust / build caches that belong in .gitignore.
MACHINE_DIRS = ("__pycache__", ".venv", ".pytest_cache", "node_modules")

# Knowledge-layer files that should exist at an active repo root.
KNOWLEDGE_REQUIRED = ("MEMORY.md",)

# Secret-shaped strings. Deterministic and conservative -- err toward flagging.
SECRET_PATTERNS = (
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("openai-style key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("anthropic key", re.compile(r"sk-ant-[A-Za-z0-9-]{20,}")),
    ("slack token", re.compile(r"xox[baprs]-[0-9A-Za-z-]{10,}")),
    ("secret assignment", re.compile(
        r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*"
        r"['\"][A-Za-z0-9/\+_\-]{16,}['\"]")),
)

# Only scan human-facing docs for secrets -- NOT .env, which is meant to hold them.
DOC_SUFFIXES = (".md", ".txt", ".rst")

DEFAULT_SKIP_DIRS = {".git", "__pycache__", ".venv", ".pytest_cache",
                     "node_modules", "AgentGRIT-attic"}


@dataclass
class GardenConfig:
    secret_scan_suffixes: tuple = DOC_SUFFIXES
    secret_patterns: tuple = SECRET_PATTERNS
    knowledge_required: tuple = KNOWLEDGE_REQUIRED
    machine_dirs: tuple = MACHINE_DIRS
    skip_dirs: set = field(default_factory=lambda: set(DEFAULT_SKIP_DIRS))
    large_file_mb: float = 25.0
    map_stale_days: int = 14
    # optional: a doctrine file whose "as of YYYY-MM-DD" date is checked for staleness
    charter_path: str | None = None
    # optional: paths the charter claims exist; each missing one is drift
    asserted_paths: tuple = ()


def _iter_files(root: Path, cfg: GardenConfig):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in cfg.skip_dirs]
        for f in filenames:
            yield Path(dirpath) / f


def check_secrets_in_docs(root: Path, cfg: GardenConfig) -> list[Finding]:
    out: list[Finding] = []
    for p in _iter_files(root, cfg):
        if p.suffix.lower() not in cfg.secret_scan_suffixes:
            continue
        try:
            text = p.read_text(errors="ignore")
        except Exception:  # noqa: BLE001
            continue
        for name, rx in cfg.secret_patterns:
            if rx.search(text):
                out.append(Finding("secrets_in_docs", Severity.HIGH,
                                   str(p.relative_to(root)),
                                   f"{name} pattern found in a tracked document"))
    return out


def check_knowledge_present(root: Path, cfg: GardenConfig) -> list[Finding]:
    out: list[Finding] = []
    for req in cfg.knowledge_required:
        if not (root / req).exists():
            out.append(Finding("knowledge_present", Severity.MEDIUM, req,
                               f"{req} missing at repo root -- memory layer has no anchor"))
    return out


def check_machine_layer_hygiene(root: Path, cfg: GardenConfig) -> list[Finding]:
    """Machine exhaust that has crept into the tree where it should be gitignored."""
    out: list[Finding] = []
    gi = root / ".gitignore"
    ignored = gi.read_text().splitlines() if gi.exists() else []
    ignored_set = {ln.strip().rstrip("/") for ln in ignored
                   if ln.strip() and not ln.startswith("#")}
    for d in cfg.machine_dirs:
        if (root / d).exists() and d not in ignored_set:
            out.append(Finding("machine_layer", Severity.LOW, d,
                               f"{d}/ present but not in .gitignore -- exhaust may be tracked"))
    return out


def check_large_files(root: Path, cfg: GardenConfig) -> list[Finding]:
    out: list[Finding] = []
    limit = cfg.large_file_mb * 1024 * 1024
    for p in _iter_files(root, cfg):
        try:
            sz = p.stat().st_size
        except Exception:  # noqa: BLE001
            continue
        if sz > limit:
            sev = Severity.MEDIUM if sz > limit * 4 else Severity.LOW
            out.append(Finding("large_file", sev, str(p.relative_to(root)),
                               f"{sz / 1e6:.0f} MB inside the repo (stale backup / dead weight?)"))
    return out


def check_map_staleness(root: Path, cfg: GardenConfig) -> list[Finding]:
    if not cfg.charter_path:
        return []
    p = root / cfg.charter_path
    if not p.exists():
        return [Finding("map_staleness", Severity.LOW, cfg.charter_path,
                        "charter path configured but not found")]
    m = re.search(r"as of (\d{4})-(\d{2})-(\d{2})", p.read_text(errors="ignore"))
    if not m:
        return []
    try:
        as_of = date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return []
    age = (date.today() - as_of).days
    if age > cfg.map_stale_days:
        return [Finding("map_staleness", Severity.MEDIUM, cfg.charter_path,
                        f"environment map is {age} days old (>{cfg.map_stale_days}) -- "
                        f"reverify against the filesystem")]
    return []


def check_asserted_paths(root: Path, cfg: GardenConfig) -> list[Finding]:
    out: list[Finding] = []
    for rel in cfg.asserted_paths:
        if not (root / rel).exists():
            out.append(Finding("asserted_paths", Severity.HIGH, rel,
                               "doctrine asserts this path exists, but it does not -- map drift"))
    return out


CHECKERS = (check_secrets_in_docs, check_knowledge_present, check_machine_layer_hygiene,
            check_large_files, check_map_staleness, check_asserted_paths)


@dataclass
class GardenReport:
    root: str
    ts: str
    findings: list

    @property
    def worst(self) -> Severity:
        return max((f.severity for f in self.findings), default=Severity.INFO)

    @property
    def count(self) -> int:
        return len(self.findings)

    def by_severity(self, sev: Severity) -> list:
        return [f for f in self.findings if f.severity == sev]

    def as_dict(self) -> dict:
        return {"root": self.root, "ts": self.ts, "worst": self.worst.label,
                "count": self.count, "findings": [f.as_dict() for f in self.findings]}


def tend(root: Path, cfg: GardenConfig | None = None) -> GardenReport:
    """Run every checker over `root`. Deterministic; no side effects."""
    cfg = cfg or GardenConfig()
    findings: list = []
    for chk in CHECKERS:
        findings.extend(chk(root, cfg))
    findings.sort(key=lambda f: f.severity, reverse=True)
    return GardenReport(str(root), datetime.now().isoformat(), findings)
