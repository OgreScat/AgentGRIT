"""Tests for the in-house skill review -- automate the clearly-good and clearly-bad,
escalate only the consequential residue (secrets / unvetted code / high-stakes)."""

from dataclasses import dataclass

from src.execution.skill_review import Decision, review


@dataclass
class _Sk:
    runs_code: bool = True
    permissions: tuple = ()


def test_vetted_bounded_relevant_auto_approves():
    v = review(_Sk(runs_code=True, permissions=()), 0.9, vetted=True)
    assert v.decision is Decision.APPROVE
    assert v.auto_greenlight is True and v.requires_human is False


def test_unvetted_broad_code_auto_rejects_no_human():
    v = review(_Sk(runs_code=True, permissions=("filesystem", "network")), 0.9, vetted=False)
    assert v.decision is Decision.REJECT
    assert v.requires_human is False  # a refusal is complete


def test_secret_access_requires_human_even_if_vetted():
    v = review(_Sk(permissions=("secrets",)), 0.9, vetted=True)
    assert v.decision is Decision.REVIEW and v.requires_human is True


def test_unvetted_code_requires_human():
    v = review(_Sk(runs_code=True), 0.9, vetted=False)
    assert v.requires_human is True


def test_high_stakes_forces_review():
    v = review(_Sk(runs_code=False, permissions=()), 0.9, vetted=True, high_stakes=True)
    assert v.decision is Decision.REVIEW and v.requires_human is True


def test_low_relevance_bounded_clears_without_human():
    v = review(_Sk(runs_code=False), 0.1, vetted=True)
    assert v.decision is Decision.REVIEW
    assert v.requires_human is False and v.auto_greenlight is True
