"""idea_to_project scaffolds a governed project tree offline."""

from pathlib import Path

from src.planning.idea_to_project import scaffold_idea, slugify


def test_slugify():
    assert slugify("Build a Cost-Aware Changelog Bot!") == "build-a-cost-aware-changelog-bot"
    assert slugify("") == "untitled-idea"


def test_scaffold_creates_structure(tmp_path):
    result = scaffold_idea(
        "build a cost-aware changelog bot",
        root=tmp_path,
        include_skills=True,
    )
    assert result.path.is_dir()
    assert (result.path / "_START_HERE.md").is_file()
    assert (result.path / "MEMORY.md").is_file()
    assert (result.path / "RESEARCH_PLAN.md").is_file()
    start = (result.path / "_START_HERE.md").read_text()
    assert "cost-aware changelog" in start.lower() or "changelog" in start.lower()
    assert "_START_HERE.md" in result.files


def test_scaffold_idempotent_no_overwrite(tmp_path):
    root = tmp_path
    r1 = scaffold_idea("unique idea alpha", root=root, include_skills=False)
    (r1.path / "_START_HERE.md").write_text("KEEP ME", encoding="utf-8")
    r2 = scaffold_idea("unique idea alpha", root=root, include_skills=False)
    assert (r2.path / "_START_HERE.md").read_text() == "KEEP ME"
    assert r2.files == []  # nothing new written
