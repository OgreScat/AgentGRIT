"""Tests for the Research Quality guardrail -- the "don't act on bad research" rule.

Pins the core safety: an irreversible/high-stakes action on weak, uncorroborated
research is INSUFFICIENT and requires a human; human-sourced and corroborated
evidence is sufficient; low-stakes exploration is permissive.
"""

from datetime import datetime

from src.governance.research_quality import assess, quality_of, Verdict


def _r(provider, urls=None, content="x" * 80):
    return {"provider": provider, "urls": urls or [], "content": content,
            "ts": datetime.now().isoformat()}


def test_human_beats_open_web():
    assert quality_of(_r("human")) > quality_of(_r("duckduckgo"))


def test_primary_domain_boosts_quality():
    base = quality_of(_r("brave", urls=["http://example.com"]))
    primary = quality_of(_r("brave", urls=["https://docs.python.org/3/"]))
    assert primary > base


def test_wikipedia_lowers_quality():
    base = quality_of(_r("brave", urls=["http://example.com"]))
    wiki = quality_of(_r("brave", urls=["https://en.wikipedia.org/wiki/Foo"]))
    assert wiki < base


def test_irreversible_on_single_weak_is_insufficient():
    a = assess([_r("duckduckgo", urls=["http://blog"])], high_stakes=True, reversible=False)
    assert a.verdict is Verdict.INSUFFICIENT
    assert a.require_human is True


def test_irreversible_on_human_is_sufficient():
    a = assess([_r("human")], high_stakes=True, reversible=False)
    assert a.verdict is Verdict.SUFFICIENT
    assert a.require_human is False


def test_irreversible_corroborated_is_sufficient():
    results = [_r("brave", urls=["https://docs.python.org/3/"]), _r("perplexity")]
    a = assess(results, high_stakes=True, reversible=False)
    assert a.verdict is Verdict.SUFFICIENT


def test_no_evidence_high_stakes_insufficient():
    a = assess([], high_stakes=True, reversible=False)
    assert a.verdict is Verdict.INSUFFICIENT
    assert a.require_human is True


def test_low_stakes_single_weak_is_ok():
    a = assess([_r("duckduckgo")], high_stakes=False, reversible=True)
    assert a.verdict is Verdict.SUFFICIENT


# --- Conflict detection (CONTESTED) --------------------------------------------

_AFFIRM_TXT = ("vaccine schedule immunity dosage confirmed effective "
               "supported proven verified studies")
_DENY_TXT = ("vaccine schedule immunity dosage refuted ineffective "
             "debunked unproven harmful contrary")


def test_concordant_corroboration_still_sufficient():
    # two high-trust sources that AGREE (both affirm) -> not contested
    results = [_r("perplexity", content=_AFFIRM_TXT),
               _r("grok", content=_AFFIRM_TXT)]
    a = assess(results, high_stakes=True, reversible=False)
    assert a.verdict is Verdict.SUFFICIENT


def test_discordant_corroboration_is_contested():
    # two high-trust sources on the SAME topic asserting OPPOSITE conclusions
    results = [_r("perplexity", content=_AFFIRM_TXT),
               _r("grok", content=_DENY_TXT)]
    a = assess(results, high_stakes=True, reversible=False)
    assert a.verdict is Verdict.CONTESTED
    assert a.require_human is True


def test_neutral_corroboration_unaffected():
    # default 'x'*80 content is neutral polarity -> never contested
    results = [_r("brave", urls=["https://docs.python.org/3/"]), _r("perplexity")]
    a = assess(results, high_stakes=True, reversible=False)
    assert a.verdict is Verdict.SUFFICIENT


def test_conflict_among_weak_sources_not_contested():
    # low-trust sources below the corroboration tier don't trigger CONTESTED;
    # a single weak source on an irreversible action stays INSUFFICIENT
    results = [_r("duckduckgo", content=_AFFIRM_TXT),
               _r("duckduckgo", content=_DENY_TXT, urls=["http://b"])]
    a = assess(results, high_stakes=True, reversible=False)
    assert a.verdict is not Verdict.CONTESTED


def test_low_stakes_conflict_is_ignored():
    results = [_r("perplexity", content=_AFFIRM_TXT),
               _r("grok", content=_DENY_TXT)]
    a = assess(results, high_stakes=False, reversible=True)
    assert a.verdict is Verdict.SUFFICIENT


def test_single_strong_source_never_contested():
    a = assess([_r("human", content=_DENY_TXT)], high_stakes=True, reversible=False)
    assert a.verdict is Verdict.SUFFICIENT
