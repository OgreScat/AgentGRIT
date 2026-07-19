"""Sentinel Phase Zero scanner. Fail-closed: errors scan as HOLD, never ALLOW."""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .patterns import BLOCK_PATTERNS, HOLD_PATTERNS, LIMIT_PATTERNS, SCAN_SUFFIXES


class Verdict(str, Enum):
    ALLOW = "allow"
    LIMIT = "allow_limited"
    HOLD = "hold"
    BLOCK = "block"


def _mask(excerpt: str) -> str:
    """Never reproduce a matched secret — show a stub only."""
    e = excerpt.strip()
    return (e[:6] + "…[masked " + str(max(0, len(e) - 6)) + " chars]") if len(e) > 10 else "[masked]"


@dataclass
class Finding:
    path: str
    line: int
    pattern_id: str
    severity: str          # block | hold | limit
    label: str
    excerpt: str           # masked for block-class

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class SentinelReport:
    verdict: Verdict
    findings: list[Finding] = field(default_factory=list)
    files_scanned: int = 0
    file_hashes: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    ts: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "verdict": self.verdict.value,
            "files_scanned": self.files_scanned,
            "findings": [f.to_dict() for f in self.findings],
            "file_hashes": self.file_hashes,
            "errors": self.errors,
        }


def _scan_text(rel: str, text: str, findings: list[Finding]) -> None:
    for lineno, line in enumerate(text.splitlines(), 1):
        for pid, pat, label in BLOCK_PATTERNS:
            m = pat.search(line)
            if m:
                findings.append(Finding(rel, lineno, pid, "block", label, _mask(m.group(0))))
        for pid, pat, label in HOLD_PATTERNS:
            if pat.search(line):
                findings.append(Finding(rel, lineno, pid, "hold", label, line.strip()[:120]))
        for pid, pat, label in LIMIT_PATTERNS:
            if pat.search(line):
                findings.append(Finding(rel, lineno, pid, "limit", label, line.strip()[:120]))


def scan_paths(paths: list[Path], *, root: Path | None = None,
               ledger_dir: Path | None = None) -> SentinelReport:
    """Scan files/trees. Any read error -> HOLD (fail closed). Appends ledger."""
    report = SentinelReport(verdict=Verdict.ALLOW)
    files: list[Path] = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            files += [f for f in sorted(p.rglob("*"))
                      if f.is_file() and f.suffix.lower() in SCAN_SUFFIXES
                      and ".git" not in f.parts and "__pycache__" not in f.parts]
        elif p.is_file():
            files.append(p)
        else:
            report.errors.append(f"missing: {p}")
    for f in files:
        rel = str(f.relative_to(root)) if root and root in f.parents else str(f)
        try:
            data = f.read_bytes()
            report.file_hashes[rel] = hashlib.sha256(data).hexdigest()
            _scan_text(rel, data.decode("utf-8", errors="replace"), report.findings)
            report.files_scanned += 1
        except Exception as exc:  # noqa: BLE001 — fail closed
            report.errors.append(f"{rel}: {type(exc).__name__}")
    sevs = {f.severity for f in report.findings}
    if "block" in sevs:
        report.verdict = Verdict.BLOCK
    elif "hold" in sevs or report.errors:
        report.verdict = Verdict.HOLD
    elif "limit" in sevs:
        report.verdict = Verdict.LIMIT
    else:
        report.verdict = Verdict.ALLOW
    try:
        from src.utils.logging import write_jsonl
        write_jsonl("sentinel.jsonl", report.to_dict(),
                    log_dir=ledger_dir) if ledger_dir else write_jsonl("sentinel.jsonl", report.to_dict())
    except Exception:
        pass  # ledger failure must not change the verdict
    return report


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m src.sentinel.scan <path> [path...]")
        return 2
    report = scan_paths([Path(a) for a in args], root=Path.cwd())
    print(json.dumps(report.to_dict(), indent=2))
    return {"allow": 0, "allow_limited": 0, "hold": 3, "block": 4}[report.verdict.value]


if __name__ == "__main__":
    raise SystemExit(main())
