"""Repo Steward -- AgentGRIT's first turnkey governed agent.

A governed *advisor* (not an auto-editor). It composes existing primitives:

  * gardener.tend()              -- real repo hygiene findings
  * skill_discovery.discover_local() -- propose-only local skills
  * autonomy.classify_action_risk / decide / must_stop -- gate each proposal
  * decision_record.record()     -- one auditable record per run

It NEVER edits, deletes, or rewrites files. Destructive remediations are
proposed as action strings, classified, and ESCALATED via must_stop when
HIGH/CRITICAL. Report-only findings PROCEED as advice.

Template pattern preserved (persona + bylaw wrap around run_once), matching
src/agents/example_agent.py.

CLI:
  python -m src.agents.repo_steward_agent [DIR]
  make agent-steward DIR=.

Orchestrator:
  python -m src.main --agent repo_steward
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..governance.bylaws import get_bylaw_engine, AgentRole, BylawAction
from ..governance.persona import render_persona_block


# ── Proposal mapping (finding → remediation action text) ──────────────────────

def _proposal_for(finding: Any) -> tuple[str, bool]:
    """Return (action_text, is_destructive_proposal).

    Destructive proposals deliberately use words the autonomy classifier treats
    as HIGH (delete/rm -rf/rotate/rewrite) so they must_stop. Report-only
    proposals stay LOW and may proceed as advice.
    """
    checker = getattr(finding, "checker", "") or ""
    path = getattr(finding, "path", "") or ""
    detail = getattr(finding, "detail", "") or ""
    sev = getattr(getattr(finding, "severity", None), "label", "") or ""

    if checker == "secrets_in_docs":
        # Destructive proposal: rotate + rewrite — human must approve.
        return (
            f"delete secrets from {path} and rotate the leaked credentials "
            f"({detail})",
            True,
        )
    if checker == "large_file":
        return (
            f"rm -rf {path} to reclaim disk ({detail})",
            True,
        )
    if checker == "knowledge_present":
        return (
            f"report missing knowledge file {path}: create MEMORY.md after review",
            False,
        )
    if checker == "machine_layer":
        return (
            f"report untracked machine-layer path {path}: add to .gitignore",
            False,
        )
    if checker == "map_staleness":
        return (
            f"report stale doctrine map at {path}: refresh as-of date after human verify",
            False,
        )
    if checker == "asserted_paths":
        return (
            f"report missing asserted path {path}: document drift or restore file",
            False,
        )
    # Unknown checker — fail-safe report only
    return (
        f"report gardener finding [{sev}/{checker}] at {path}: {detail}",
        False,
    )


@dataclass
class GatedProposal:
    finding: dict
    action: str
    risk: int
    gate: str
    reason: str
    escalated: bool

    def as_dict(self) -> dict:
        return {
            "finding": self.finding,
            "action": self.action,
            "risk": self.risk,
            "gate": self.gate,
            "reason": self.reason,
            "escalated": self.escalated,
        }


@dataclass
class StewardReport:
    root: str
    status: str
    finding_count: int
    worst: str
    proposals: list[GatedProposal] = field(default_factory=list)
    skills: list[dict] = field(default_factory=list)
    decision_disposition: str | None = None
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            "REPO STEWARD REPORT  ·  governed advisor (no auto-edit)",
            "=" * 56,
            f"  root:     {self.root}",
            f"  status:   {self.status}",
            f"  findings: {self.finding_count}  (worst={self.worst})",
            f"  decision: {self.decision_disposition or 'n/a'}",
            "",
            "FINDINGS & PROPOSED ACTIONS",
            "-" * 56,
        ]
        if not self.proposals:
            lines.append("  (none)")
        for i, p in enumerate(self.proposals, 1):
            f = p.finding
            mark = "⤴ ESCALATE" if p.escalated else "✓ advice"
            lines.append(
                f"  {i}. [{f.get('severity')}/{f.get('checker')}] {f.get('path')}"
            )
            lines.append(f"     detail:   {f.get('detail')}")
            lines.append(f"     propose:  {p.action}")
            lines.append(
                f"     autonomy: {mark}  gate={p.gate} risk={p.risk} — {p.reason}"
            )
            lines.append("")

        lines.append("LOCAL SKILLS (propose-only, not installed)")
        lines.append("-" * 56)
        if not self.skills:
            lines.append("  (none matched)")
        for s in self.skills:
            lines.append(
                f"  • {s.get('name')} [{s.get('pass')}] "
                f"score={s.get('score')} → {s.get('decision')}"
            )

        if self.notes:
            lines.append("")
            lines.append("NOTES")
            lines.append("-" * 56)
            for n in self.notes:
                lines.append(f"  • {n}")

        lines.append("")
        lines.append(
            "This agent does NOT edit files. Apply escalated remediations only "
            "after human approval."
        )
        lines.append("=" * 56)
        return "\n".join(lines)


def _parse_target(task: str, default: Path | None = None) -> Path:
    """Extract a directory path from the task string; default = cwd."""
    text = (task or "").strip()
    # Common forms: "steward inspect /path", "inspect /path", bare path
    tokens = text.split()
    candidates: list[str] = []
    for t in tokens:
        if t.startswith("-"):
            continue
        if t.lower() in ("steward", "inspect", "repo", "steward:", "dir", "path"):
            continue
        candidates.append(t)
    for c in reversed(candidates):
        p = Path(c).expanduser()
        if p.is_dir():
            return p.resolve()
    # Last token as path even if not yet existing? Prefer existing only.
    base = default if default is not None else Path.cwd()
    return base.resolve()


class RepoStewardAgent:
    """Turnkey governed advisor: garden → propose → gate → record → report."""

    def __init__(self, project_key: str | None = None):
        self.project_key = project_key
        self.bylaws = get_bylaw_engine(AgentRole.DEVELOPER)

    def build_prompt(self, task: str) -> str:
        persona_block = render_persona_block(self.project_key)
        return f"{persona_block}\n\n---\n\nTASK: {task}"

    async def run_once(
        self,
        task: str,
        *,
        target: Path | None = None,
        garden_config: Any = None,
    ) -> dict:
        """
        One steward cycle. Never raises into the orchestrator (fail-safe envelope).
        Returns an evidence bundle with a human-readable report.

        garden_config: optional gardener.GardenConfig (tests lower large_file_mb).
        """
        try:
            return await self._run_once_inner(
                task, target=target, garden_config=garden_config,
            )
        except Exception as exc:  # noqa: BLE001 — agent must not crash orchestrator
            return {
                "status": "error",
                "reason": f"repo_steward failed safe: {exc}",
                "evidence": {
                    "task": task,
                    "report": f"REPO STEWARD ERROR\n{exc}",
                    "provider": "local",
                    "cost": 0.0,
                },
            }

    async def _run_once_inner(
        self,
        task: str,
        *,
        target: Path | None = None,
        garden_config: Any = None,
    ) -> dict:
        # 1. Bylaw wrap (same contract as TemplateAgent)
        bylaw_result = self.bylaws.evaluate(command=task, action_type="bash")
        if bylaw_result.action == BylawAction.BLOCK:
            return {"status": "blocked", "reason": bylaw_result.reason}
        if bylaw_result.action == BylawAction.ESCALATE:
            return {"status": "escalate", "reason": bylaw_result.reason}

        # Persona is built for the evidence trail (no LLM call — steward is deterministic)
        _ = self.build_prompt(task)

        root = target if target is not None else _parse_target(task)
        try:
            root_display = str(root.relative_to(Path.cwd())) or "."
        except ValueError:
            # Outside cwd — show basename only in report (avoid leaking host paths)
            root_display = root.name or str(root)
        notes: list[str] = [
            "Mode: governed advisor — zero file mutations in this version.",
            f"Target: {root_display}",
        ]

        # 2. Gardener (reuse — do not reimplement checkers)
        from ..governance.gardener import tend, GardenConfig, Severity

        garden_cfg = garden_config if garden_config is not None else GardenConfig()
        report = tend(root, garden_cfg)

        # 3. Skill discovery (propose-only)
        skills_out: list[dict] = []
        try:
            from ..execution.skill_discovery import discover_local
            for c in discover_local(task or "repo hygiene steward", top=5):
                skills_out.append({
                    "name": c.skill.name,
                    "pass": c.pass_name,
                    "score": c.score,
                    "decision": c.decision,
                })
        except Exception as exc:  # noqa: BLE001
            notes.append(f"skill_discovery unavailable: {exc}")

        # 4. Gate each proposed remediation via autonomy
        from ..governance.autonomy import (
            classify_action_risk,
            decide,
            must_stop,
        )
        from ..governance.trust import get_trust_manager, TrustLevel

        try:
            trust = get_trust_manager().get_trust_level("repo_steward")
        except Exception:  # noqa: BLE001
            trust = TrustLevel.TRUSTED

        proposals: list[GatedProposal] = []
        any_escalated = False
        for finding in report.findings:
            action, _destructive = _proposal_for(finding)
            # Bylaw-evaluate the *proposal* so classify can see ESCALATE/BLOCK
            prop_bylaw = self.bylaws.evaluate(command=action, action_type="bash")
            risk = classify_action_risk(action, bylaw_result=prop_bylaw)
            auto = decide(
                risk=risk,
                trust=trust,
                bylaw_action=prop_bylaw.action,
            )
            escalated = must_stop(auto)
            if escalated:
                any_escalated = True
            proposals.append(GatedProposal(
                finding=finding.as_dict() if hasattr(finding, "as_dict") else {
                    "checker": getattr(finding, "checker", ""),
                    "severity": getattr(getattr(finding, "severity", None), "label", ""),
                    "path": getattr(finding, "path", ""),
                    "detail": getattr(finding, "detail", ""),
                },
                action=action,
                risk=risk,
                gate=auto.gate.value,
                reason=auto.reason,
                escalated=escalated,
            ))

        # 5. ONE decision_record per run
        rec_disposition = None
        try:
            from ..governance.decision_record import record as _record

            class _Route:
                provider = "local"
                category = "repo_steward"
                confidence = 1.0
                estimated_cost = 0.0
                reason = (
                    f"steward tend({root_display}): {report.count} findings, "
                    f"{sum(1 for p in proposals if p.escalated)} escalated"
                )

            class _Evidence:
                verdict = "insufficient" if any_escalated else "sufficient"
                score = 1.0 if report.count == 0 else 0.5
                require_human = any_escalated
                reason = (
                    f"{sum(1 for p in proposals if p.escalated)} remediation(s) "
                    f"require human approval; steward does not auto-edit"
                )

            # Overall bylaw for the steward run itself
            rec = _record(
                action=f"repo_steward inspect {root_display}"[:200],
                routing=_Route(),
                bylaw=bylaw_result if not any_escalated else type(
                    "B", (), {"action": BylawAction.ESCALATE,
                              "reason": "one or more remediations require human approval"}
                )(),
                evidence=_Evidence(),
                authorized_by="agent:repo_steward",
                project=self.project_key,
            )
            rec_disposition = getattr(
                getattr(rec, "disposition", None), "value", None
            )
        except Exception as exc:  # noqa: BLE001 — audit must never break the agent
            notes.append(f"decision_record write skipped: {exc}")

        worst = report.worst.label if report.findings else Severity.INFO.label
        steward = StewardReport(
            root=root_display,
            status="done",
            finding_count=report.count,
            worst=worst,
            proposals=proposals,
            skills=skills_out,
            decision_disposition=rec_disposition,
            notes=notes,
        )
        text = steward.render()

        return {
            "status": "done",
            "evidence": {
                "task": task,
                "root": root_display,
                "report": text,
                "finding_count": report.count,
                "worst": worst,
                "proposals": [p.as_dict() for p in proposals],
                "skills": skills_out,
                "decision_disposition": rec_disposition,
                "provider": "local",
                "cost": 0.0,
                "auto_edit": False,
            },
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Repo Steward — governed advisor (gardener + autonomy, no auto-edit)",
    )
    parser.add_argument(
        "dir",
        nargs="?",
        default=".",
        help="Target directory to inspect (default: cwd)",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Optional project_key for persona/context",
    )
    args = parser.parse_args(argv)
    target = Path(args.dir).expanduser().resolve()
    if not target.is_dir():
        print(f"error: not a directory: {target}")
        return 2

    agent = RepoStewardAgent(project_key=args.project)
    task = f"steward inspect {target}"
    result = asyncio.run(agent.run_once(task, target=target))
    report = (result.get("evidence") or {}).get("report") or result.get("reason") or ""
    print(report)
    return 0 if result.get("status") in ("done", "blocked", "escalate") else 1


if __name__ == "__main__":
    raise SystemExit(main())
