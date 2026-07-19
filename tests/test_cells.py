"""Cells Interlinked — interlocks fail closed."""
from src.cells import CellsRun, NextState, validate_run


def _base() -> CellsRun:
    return CellsRun(
        task={"deliverable": "fix auth check", "risk": "local_reversible"},
        context={"facts": ["failure isolated to test suite"]},
        quality={"acceptance": ["unauthorized deletion rejected"]},
        scope={"in": ["auth service"], "out": ["schema migration"]},
        evidence={"items": ["pytest exit 0", "diff auth.py"]},
        checkpoint={"result": "pass"},
        report={"result": "patched", "claims": [{"text": "tests pass", "label": "CERTAIN"}]},
        next_state=NextState.COMPLETED.value,
        modes=("workflow",),
    )


def test_valid_run_passes():
    assert validate_run(_base()) == []


def test_completion_requires_evidence_and_checkpoint():
    r = _base(); r.evidence = {}
    assert any("without named evidence" in x for x in validate_run(r))
    r = _base(); r.checkpoint = {"result": "revise"}
    assert any("passing checkpoint" in x for x in validate_run(r))


def test_delegation_requires_bounds():
    r = _base(); r.modes = ("workflow", "parallel")
    r.delegation = [{"objective": "scan docs"}]
    out = validate_run(r)
    assert any("missing allowed_tools" in x for x in out)
    assert any("missing budget" in x for x in out)


def test_claims_need_reference_or_label():
    r = _base()
    r.report["claims"].append({"text": "prices will rise"})
    assert any("claim without reference" in x for x in validate_run(r))


def test_overlay_loading():
    r = _base(); r.modes = ("multi_session",)
    assert any("continuity" in x for x in validate_run(r))
