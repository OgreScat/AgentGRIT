"""Tests for the native Pillar Inspector -- the governance self-check.

These pin the headline behavior: the Fabrication pillar judges evidence QUALITY
(not mere presence), and irreversible actions on weak evidence fail it.
"""

from src.governance.pillars import inspect, Proposal, Pillar


def test_clean_action_grades_A():
    sc = inspect(Proposal(action="add docstrings", evidence="style guide",
                          evidence_quality=0.9, intent="readability"))
    assert sc.grade == "A"
    assert not sc.flagged()


def test_no_evidence_fails_fabrication():
    sc = inspect(Proposal(action="claim X", evidence="", intent="assert"))
    fab = [r for r in sc.results if r.pillar is Pillar.FABRICATION][0]
    assert fab.passed is False


def test_weak_evidence_fails_fabrication():
    # evidence present but below the quality bar -> Fabrication must fail
    sc = inspect(Proposal(action="delete artifacts", evidence="one weak hit",
                          evidence_quality=0.4, intent="cleanup"))
    fab = [r for r in sc.results if r.pillar is Pillar.FABRICATION][0]
    assert fab.passed is False


def test_strong_evidence_passes_fabrication():
    sc = inspect(Proposal(action="apply patch", evidence="cited docs",
                          evidence_quality=0.85, intent="fix"))
    fab = [r for r in sc.results if r.pillar is Pillar.FABRICATION][0]
    assert fab.passed is True


def test_irreversible_flags_unpredictability():
    sc = inspect(Proposal(action="delete", evidence="x", evidence_quality=0.9,
                          reversible=False))
    unp = [r for r in sc.results if r.pillar is Pillar.UNPREDICTABILITY][0]
    assert unp.passed is False


def test_forbidden_path_flags_manipulation():
    sc = inspect(Proposal(action="rotate key", evidence="x", evidence_quality=0.9,
                          touches_forbidden=True))
    man = [r for r in sc.results if r.pillar is Pillar.MANIPULATION][0]
    assert man.passed is False


def test_scorecard_grade_boundaries():
    # all pass -> A
    good = inspect(Proposal(action="format", evidence="guide", evidence_quality=0.9))
    assert good.score == 1.0
