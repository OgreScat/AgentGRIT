"""Repo Steward -- first turnkey agent; composes gardener + autonomy + records."""

import json
from pathlib import Path

import pytest

from src.agents.repo_steward_agent import RepoStewardAgent, _proposal_for
from src.governance.gardener import GardenConfig, Finding, Severity
from src.governance.autonomy import classify_action_risk, decide, must_stop


def _plant_fixture(root: Path) -> None:
    """Plant a large file + a secret-looking doc line (real gardener inputs)."""
    (root / "MEMORY.md").write_text("# memory\n", encoding="utf-8")
    # Secret pattern: secret assignment (matches gardener SECRET_PATTERNS)
    (root / "NOTES.md").write_text(
        "api_key = 'AKIAABCDEFGHIJKLMNOP'\n",
        encoding="utf-8",
    )
    # Large file: 2MB with threshold 1MB in GardenConfig
    (root / "blob.bin").write_bytes(b"\0" * (2 * 1024 * 1024))


def test_proposal_destructive_secrets_escalates():
    f = Finding(
        "secrets_in_docs", Severity.HIGH, "NOTES.md",
        "aws access key pattern found in a tracked document",
    )
    action, destructive = _proposal_for(f)
    assert destructive
    risk = classify_action_risk(action)
    assert risk >= 30
    d = decide(risk=risk, trust="autonomous")
    assert must_stop(d)


def test_proposal_report_only_proceeds():
    f = Finding(
        "knowledge_present", Severity.MEDIUM, "MEMORY.md",
        "required knowledge file missing",
    )
    action, destructive = _proposal_for(f)
    assert not destructive
    risk = classify_action_risk(action)
    assert risk < 30
    d = decide(risk=risk, trust="trusted")
    assert not must_stop(d)


@pytest.mark.asyncio
async def test_steward_run_on_fixture(tmp_path, monkeypatch):
    _plant_fixture(tmp_path)
    # Capture decision records without polluting repo logs/
    written: list[dict] = []

    def fake_write_jsonl(name, entry, log_dir=None):
        written.append({"name": name, "entry": entry})

    monkeypatch.setattr("src.utils.logging.write_jsonl", fake_write_jsonl)

    agent = RepoStewardAgent()
    cfg = GardenConfig(large_file_mb=1.0)
    result = await agent.run_once(
        task=f"steward inspect {tmp_path}",
        target=tmp_path,
        garden_config=cfg,
    )

    assert result["status"] == "done"
    ev = result["evidence"]
    assert ev["auto_edit"] is False
    assert ev["finding_count"] >= 2  # secret + large file at minimum
    assert ev["provider"] == "local"
    assert ev["cost"] == 0.0

    proposals = ev["proposals"]
    assert proposals
    escalated = [p for p in proposals if p["escalated"]]
    proceeded = [p for p in proposals if not p["escalated"]]
    # Destructive remediations (secrets / large file) must escalate
    assert escalated, "expected at least one escalated remediation"
    assert any(
        "secret" in p["action"].lower() or "rm -rf" in p["action"].lower()
        or "rotate" in p["action"].lower()
        for p in escalated
    )
    # Report must render
    report = ev["report"]
    assert "REPO STEWARD REPORT" in report
    assert "ESCALATE" in report or "⤴" in report
    assert "no auto-edit" in report.lower() or "does NOT edit" in report

    # decision_record written once (authorized_by agent:repo_steward)
    steward_recs = [
        w for w in written
        if w["name"] == "decisions.jsonl"
        and (w["entry"].get("authorized_by") == "agent:repo_steward")
    ]
    assert len(steward_recs) == 1
    assert steward_recs[0]["entry"].get("disposition") in (
        "escalated", "proceed", "refused", "contested",
    )
    # With secrets present, human required → escalated disposition
    assert steward_recs[0]["entry"].get("disposition") == "escalated"
    assert ev["decision_disposition"] == "escalated"

    # proceeded list may be empty if every finding was destructive — that's fine
    _ = proceeded


@pytest.mark.asyncio
async def test_steward_fail_safe_on_bad_root(monkeypatch):
    """Agent errors must not raise into the orchestrator."""
    agent = RepoStewardAgent()

    def boom(*a, **k):
        raise RuntimeError("simulated gardener failure")

    monkeypatch.setattr("src.governance.gardener.tend", boom)
    result = await agent.run_once(task="steward inspect /tmp", target=Path("/tmp"))
    assert result["status"] == "error"
    assert "failed safe" in result.get("reason", "")
