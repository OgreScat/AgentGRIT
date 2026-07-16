"""Repository hygiene — tracked text files must carry no personal residue.

Generic patterns only (a public repo must never enumerate real private
vocabulary — the list itself would be the leak). No secret values printed.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

FORBIDDEN = re.compile(
    r"(sk-[A-Za-z0-9]{20,}"                        # secret-shaped strings
    r"|/Users/[a-z0-9_]+/"                          # personal home paths
    r"|/Volumes/[A-Za-z0-9_-]+/"                    # local volume paths
    r"|[a-z0-9._%+-]+@(gmail|icloud|yahoo)\.com"    # personal emails
    r"|@[a-z]+\.lan\b)",                            # LAN hostnames
    re.I,
)

TEXT_SUFFIXES = {".py", ".md", ".toml", ".yaml", ".yml", ".json", ".txt", ".cfg", ".ini", ".sh"}
def _is_blocked(path: Path) -> bool:
    name = path.name.lower()
    parts = {p.lower() for p in path.parts}
    if ".obsidian" in parts:
        return True
    if name == ".env":  # .env.example is fine; a real .env is not
        return True
    return "id_rsa" in name or name.endswith(".pem")


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True,
    )
    return [REPO / line for line in out.stdout.splitlines() if line.strip()]


def test_no_personal_residue_in_tracked_text():
    hits: list[str] = []
    for f in _tracked_files():
        if f.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if FORBIDDEN.search(line):
                # report location only — never the matched value
                hits.append(f"{f.relative_to(REPO)}:{i}")
    assert not hits, f"personal residue in tracked files: {hits}"


def test_no_blocked_files_tracked():
    bad = []
    for f in _tracked_files():
        if _is_blocked(f):
            bad.append(str(f.relative_to(REPO)))
    assert not bad, f"blocked files tracked: {bad}"
