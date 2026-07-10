"""config_loader defaults + per-project research thresholds."""

from pathlib import Path

from src.governance.config_loader import (
    load_budget_config,
    load_priorities_config,
    load_project_research_thresholds,
    DEFAULT_BUDGET,
    DEFAULT_RESEARCH_THRESHOLDS,
)
from src.governance.research_quality import assess, Verdict
from src.execution.skill_discovery import load_catalog_from_dir, discover_local
from src.agents.daily_debrief_agent import run_debrief_and_notify, build_debrief


def test_budget_defaults_match_governor_when_no_override(monkeypatch, tmp_path):
    monkeypatch.setenv("GRIT_CONFIG_DIR", str(tmp_path / "missing"))
    for k in ("GRIT_SOFT_BUDGET", "GRIT_ESCALATE_BUDGET", "GRIT_HARD_CEILING",
              "RESEARCH_MAX_PAID_PER_DAY"):
        monkeypatch.delenv(k, raising=False)
    cfg = load_budget_config()
    assert cfg["soft_budget"] == DEFAULT_BUDGET["soft_budget"]
    assert cfg["escalate_budget"] == DEFAULT_BUDGET["escalate_budget"]
    assert cfg["hard_ceiling"] == DEFAULT_BUDGET["hard_ceiling"]


def test_project_research_thresholds_override(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "config"
    proj_dir = cfg_dir / "projects"
    proj_dir.mkdir(parents=True)
    (proj_dir / "strictproj.yaml").write_text(
        "strong: 0.95\ncorroborated: 0.80\nadequate: 0.70\n"
    )
    monkeypatch.setenv("GRIT_CONFIG_DIR", str(cfg_dir))
    thr = load_project_research_thresholds("strictproj")
    assert thr["strong"] == 0.95
    # Without project, env defaults
    monkeypatch.delenv("GRIT_EVIDENCE_STRONG", raising=False)
    base = load_project_research_thresholds(None)
    assert base["strong"] == DEFAULT_RESEARCH_THRESHOLDS["strong"]


def test_assess_respects_project_threshold(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "config"
    proj_dir = cfg_dir / "projects"
    proj_dir.mkdir(parents=True)
    # Set bar impossibly high so even human-tier fails irreversible
    (proj_dir / "strictproj.yaml").write_text("strong: 0.99\ncorroborated: 0.98\n")
    monkeypatch.setenv("GRIT_CONFIG_DIR", str(cfg_dir))
    now = "2026-07-09T12:00:00"
    results = [{
        "provider": "brave",
        "content": "x" * 100,
        "urls": ["https://docs.python.org/3/"],
        "ts": now,
    }]
    a = assess(results, high_stakes=True, reversible=False, project="strictproj")
    assert a.verdict in (Verdict.INSUFFICIENT, Verdict.CONTESTED)
    assert a.require_human


def test_skills_dir_loads_example():
    catalog = load_catalog_from_dir()
    names = {s.name for s in catalog}
    assert any("format" in n.lower() or "example" in n.lower() for n in names)
    hits = discover_local("format and lint python source files")
    assert isinstance(hits, list)


def test_debrief_notify_flag_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTIFY_CHANNEL", "none")
    text = run_debrief_and_notify(day="2099-01-01", log_dir=tmp_path, notify=True)
    assert "DAILY DEBRIEF" in text
