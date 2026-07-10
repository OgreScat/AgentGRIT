#!/usr/bin/env python3
"""Nightly GRIT gardener runner.

Runs the deterministic checkers over one or more repo roots, writes a JSONL log and a
rendered GARDEN-REPORT.md per repo, and honors the autonomy threshold: HIGH findings
are escalated (Zeroth Law); LOW / MEDIUM are logged for review. Schedule at 03:00.

    python3 scripts/gardener.py [ROOT ...]
    make garden

A repo may pin its own config in a .garden.json at its root (charter_path,
asserted_paths, thresholds, extra skip_dirs).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.governance.gardener import GardenConfig, GardenReport, Severity, tend  # noqa: E402


def _render_md(report: GardenReport) -> str:
    lines = [f"# Garden report -- {report.root}",
             f"_generated {report.ts} | worst: {report.worst.label} | "
             f"{report.count} findings_", ""]
    if not report.findings:
        lines.append("Nothing to report -- the memory layer is clean.")
        return "\n".join(lines) + "\n"
    for sev in (Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO):
        group = report.by_severity(sev)
        if not group:
            continue
        lines.append(f"## {sev.label} ({len(group)})")
        for f in group:
            lines.append(f"- **{f.checker}** -- `{f.path}` -- {f.detail}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _load_cfg(root: Path) -> GardenConfig:
    cfg = GardenConfig()
    cfgfile = root / ".garden.json"
    if cfgfile.exists():
        try:
            data = json.loads(cfgfile.read_text())
            merged = {**cfg.__dict__, **data}
            if "skip_dirs" in data:
                merged["skip_dirs"] = set(data["skip_dirs"]) | set(cfg.skip_dirs)
            cfg = GardenConfig(**merged)
        except Exception:  # noqa: BLE001
            pass
    return cfg


def run_one(root: Path) -> GardenReport:
    report = tend(root, _load_cfg(root))
    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    with (logs / "gardener.jsonl").open("a") as fh:
        fh.write(json.dumps(report.as_dict()) + "\n")
    (root / "GARDEN-REPORT.md").write_text(_render_md(report))
    return report


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv[1:]] or [ROOT]
    highest = Severity.INFO
    summaries = []
    for root in roots:
        if not root.exists():
            continue
        report = run_one(root)
        highest = max(highest, report.worst)
        summaries.append(f"{root.name}: {report.worst.label} ({report.count})")

    summary = " | ".join(summaries) or "no roots"
    print(f"[gardener {datetime.now():%Y-%m-%d %H:%M}] {summary}")

    # Autonomy threshold: HIGH escalates to the human; the rest is logged.
    if highest >= Severity.HIGH:
        msg = f"Gardener HIGH finding -- {summary}. See GARDEN-REPORT.md."
        try:
            from src.utils.notify import notify
            notify(msg)
        except Exception:  # noqa: BLE001
            print("ESCALATE:", msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
