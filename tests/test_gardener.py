"""Tests for the GRIT gardener -- the mechanical checkers behind 'a rule without a
checker does not exist'.

Every checker is deterministic and runs against a tmp_path tree, so the suite never
touches the real repos or the network.
"""

from datetime import date, timedelta

from src.governance.gardener import (
    GardenConfig, Severity, check_asserted_paths, check_knowledge_present,
    check_large_files, check_machine_layer_hygiene, check_map_staleness,
    check_secrets_in_docs, tend,
)


def test_detects_secret_in_doc(tmp_path):
    (tmp_path / "TOOLS.md").write_text("api_key = 'AKIAABCDEFGHIJKLMNOP'\n")
    findings = check_secrets_in_docs(tmp_path, GardenConfig())
    assert any(f.severity is Severity.HIGH for f in findings)


def test_clean_doc_has_no_secret(tmp_path):
    (tmp_path / "NOTES.md").write_text("the key insight is to stay in the game\n")
    assert check_secrets_in_docs(tmp_path, GardenConfig()) == []


def test_missing_memory_flagged(tmp_path):
    findings = check_knowledge_present(tmp_path, GardenConfig())
    assert any(f.checker == "knowledge_present" for f in findings)


def test_memory_present_ok(tmp_path):
    (tmp_path / "MEMORY.md").write_text("# memory\n")
    assert check_knowledge_present(tmp_path, GardenConfig()) == []


def test_untracked_cache_flagged(tmp_path):
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / ".gitignore").write_text(".venv\n")  # note: __pycache__ NOT ignored
    findings = check_machine_layer_hygiene(tmp_path, GardenConfig())
    assert any(f.checker == "machine_layer" for f in findings)


def test_ignored_cache_ok(tmp_path):
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / ".gitignore").write_text("__pycache__\n.venv\n")
    assert check_machine_layer_hygiene(tmp_path, GardenConfig()) == []


def test_large_file_flagged(tmp_path):
    (tmp_path / "backup.tar").write_bytes(b"0" * (2 * 1024 * 1024))
    findings = check_large_files(tmp_path, GardenConfig(large_file_mb=1.0))
    assert any(f.checker == "large_file" for f in findings)


def test_stale_map_flagged(tmp_path):
    old = (date.today() - timedelta(days=40)).isoformat()
    (tmp_path / "SKILL.md").write_text(f"Environment map (as of {old} -- verify)\n")
    findings = check_map_staleness(
        tmp_path, GardenConfig(charter_path="SKILL.md", map_stale_days=14))
    assert any(f.checker == "map_staleness" for f in findings)


def test_fresh_map_ok(tmp_path):
    today = date.today().isoformat()
    (tmp_path / "SKILL.md").write_text(f"as of {today} -- verify\n")
    assert check_map_staleness(tmp_path, GardenConfig(charter_path="SKILL.md")) == []


def test_asserted_missing_path_is_high(tmp_path):
    findings = check_asserted_paths(
        tmp_path, GardenConfig(asserted_paths=("src/does_not_exist.py",)))
    assert findings and findings[0].severity is Severity.HIGH


def test_tend_aggregates_and_sorts_worst_first(tmp_path):
    (tmp_path / "TOOLS.md").write_text("password = 'hunter2hunter2hunter2'\n")
    report = tend(tmp_path)  # secret -> HIGH, no MEMORY.md -> MEDIUM
    assert report.worst is Severity.HIGH
    assert report.findings[0].severity >= report.findings[-1].severity
