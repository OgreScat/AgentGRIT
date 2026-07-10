"""
Research Quality layer -- how GRIT judges whether research is good enough to act on.

Free web search (even Brave) can be noisy, stale, or biased -- the "schools don't
cite Wikipedia" problem. This module scores research provenance DETERMINISTICALLY
(no opaque model) and enforces the rule that matters most:

    An irreversible or high-stakes action may NOT stand on weak, uncorroborated
    research. If the evidence is thin, GRIT escalates rather than acting on a bad
    foundation.

Everything tunable is read from env (so the publishable version can set risk
tolerance per project/bylaws without editing code). Defaults are conservative.

  GRIT_TIER_<NAME>            override a source-tier base score (e.g. GRIT_TIER_BRAVE=0.7)
  GRIT_EVIDENCE_STRONG        best-score bar for irreversible w/o corroboration (default 0.82)
  GRIT_EVIDENCE_CORROBORATED  best-score bar for irreversible WITH >=2 sources  (default 0.65)
  GRIT_EVIDENCE_ADEQUATE      best-score bar for reversible high-stakes         (default 0.62)
  GRIT_CONTRADICTION_OVERLAP  topic-overlap needed to call two sources "about the
                              same claim" before a polarity clash counts as a
                              conflict (default 0.18)

Conflict detection (the CONTESTED verdict). Corroboration is only real if the
corroborating sources AGREE. This module does NOT judge which source is right --
that is a truth claim it deliberately refuses. It only detects, deterministically
and conservatively, when two otherwise-trusted sources point in OPPOSITE
directions on the same topic, and in that case withholds the "corroborated"
discount and routes to a human instead of silently averaging a contradiction into
a green light. The signal errs toward review: it fires only when both sources are
high-trust, clearly share a subject, and clearly diverge in polarity. It will miss
subtle contradictions (false negatives) and is not a fact-checker; it is a cheap
guard against the specific failure of counting a disagreement as agreement.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

# Source tier base trust. Human-run premium research ranks highest (a person
# vetted it); open web search ranks lowest. Override any with GRIT_TIER_<NAME>.
_DEFAULT_TIER = {
    "human": 1.00,
    "grok": 0.88, "perplexity": 0.85,
    "google": 0.72,   # Google CSE — broad index; mid-trust due to documented
                      # filtering/ranking bias on some topics. Never a solo
                      # authorizer for irreversible actions (bar is 0.82).
    "brave": 0.68,
    "duckduckgo": 0.48,
    "cache": 0.58,
    "unknown": 0.30,
}


def _tier(provider: str) -> float:
    override = os.environ.get(f"GRIT_TIER_{provider.upper()}")
    if override:
        try:
            return float(override)
        except ValueError:
            pass
    return _DEFAULT_TIER.get(provider, _DEFAULT_TIER["unknown"])


def _thr(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


PRIMARY_DOMAINS = (".gov", ".edu", "docs.", "developer.", "official", "arxiv.org",
                   "nist.gov", "python.org", "owasp.org", "w3.org")
LOW_QUALITY_DOMAINS = ("wikipedia.org", "reddit.com", "quora.com", "medium.com",
                       "pinterest.", "facebook.com", "x.com", "twitter.com", "tiktok.com")


class Verdict(str, Enum):
    SUFFICIENT = "sufficient"
    WEAK = "weak"
    CONTESTED = "contested"         # trusted sources disagree; resolve/escalate
    INSUFFICIENT = "insufficient"   # must escalate; do not act


@dataclass
class Assessment:
    verdict: Verdict
    score: float
    reason: str
    require_human: bool = False


def _domain_adjust(urls: list[str]) -> float:
    adj = 0.0
    for u in urls or []:
        ul = u.lower()
        if any(d in ul for d in PRIMARY_DOMAINS):
            adj += 0.12
        elif any(d in ul for d in LOW_QUALITY_DOMAINS):
            adj -= 0.18
    return max(-0.25, min(0.25, adj))


def _recency_adjust(ts: str) -> float:
    if not ts:
        return 0.0
    try:
        age = (datetime.now() - datetime.fromisoformat(ts)).days
    except Exception:
        return 0.0
    if age <= 14:
        return 0.06
    if age <= 90:
        return 0.02
    if age > 400:
        return -0.12
    return 0.0


def quality_of(result: dict) -> float:
    """Deterministic 0..1 quality for one research result dict."""
    provider = str(result.get("provider") or "unknown").lower()
    score = _tier(provider) + _domain_adjust(result.get("urls", [])) + _recency_adjust(result.get("ts", ""))
    content = str(result.get("content") or "").strip()
    if len(content) < 60:
        score -= 0.08
    elif len(content) > 800:
        score += 0.04
    return max(0.0, min(1.0, round(score, 3)))


# Polarity cues. A source leans + if it asserts/confirms, - if it denies/refutes.
# Deliberately small and explicit -- this is a signal, not sentiment analysis.
_AFFIRM = ("confirmed", "confirms", "supported", "supports", "proven", "proves",
           "effective", "works", "safe", "verified", "valid", "true", "correct",
           "recommended", "successful", "increases", "improves", "yes")
_DENY = ("not", "no evidence", "false", "incorrect", "unsafe", "does not", "doesn't",
         "isn't", "is not", "cannot", "can't", "refuted", "debunked", "myth",
         "ineffective", "fails", "unproven", "contrary", "disproven", "decreases",
         "harmful", "denied", "denies", "never")

_STOP = frozenset(("the", "and", "for", "that", "this", "with", "from", "into", "your",
                   "have", "has", "are", "was", "were", "will", "would", "there", "their",
                   "which", "what", "when", "does", "did", "not", "but", "you", "our"))


def _count_cues(c: str, cues: tuple) -> int:
    # Single tokens matched on word boundaries; multiword phrases as substrings.
    return sum(c.count(" " + w + " ") if " " not in w else c.count(w) for w in cues)


def _polarity(content: str) -> int:
    """+1 leans affirmation, -1 leans denial, 0 neutral/mixed. Deterministic."""
    c = " " + " ".join(content.lower().split()) + " "
    aff, den = _count_cues(c, _AFFIRM), _count_cues(c, _DENY)
    if den > aff:
        return -1
    if aff > den:
        return 1
    return 0


def _salient(content: str) -> set[str]:
    """Content words >4 chars, minus stopwords -- a cheap topic fingerprint."""
    words = "".join(ch if ch.isalnum() else " " for ch in content.lower()).split()
    return {w for w in words if len(w) > 4 and w not in _STOP}


def _contradiction(scored: list, min_tier: float, overlap_thr: float) -> tuple[bool, str]:
    """Do two high-trust results share a topic but clash in polarity?

    Conservative: considers only sources at/above min_tier, requires real topic
    overlap (Jaccard >= overlap_thr) AND opposite non-zero polarity. Returns
    (fired, reason). Never asserts which source is correct.
    """
    strong = [r for s, r in scored if s >= min_tier and str(r.get("content") or "").strip()]
    for i in range(len(strong)):
        for j in range(i + 1, len(strong)):
            a, b = strong[i], strong[j]
            pa, pb = _polarity(str(a.get("content"))), _polarity(str(b.get("content")))
            if pa == 0 or pb == 0 or pa == pb:
                continue
            ta, tb = _salient(str(a.get("content"))), _salient(str(b.get("content")))
            if not ta or not tb:
                continue
            overlap = len(ta & tb) / len(ta | tb)
            if overlap >= overlap_thr:
                return True, (f"{a.get('provider')} and {b.get('provider')} share the topic "
                              f"(overlap {overlap:.2f}) but assert opposite conclusions")
    return False, ""


def assess(results: list[dict], high_stakes: bool, reversible: bool) -> Assessment:
    """Is the evidence strong enough to act on, given stakes + reversibility?"""
    strong = _thr("GRIT_EVIDENCE_STRONG", 0.82)
    corrob = _thr("GRIT_EVIDENCE_CORROBORATED", 0.65)
    adequate = _thr("GRIT_EVIDENCE_ADEQUATE", 0.62)
    overlap_thr = _thr("GRIT_CONTRADICTION_OVERLAP", 0.18)

    if not results:
        if high_stakes:
            return Assessment(Verdict.INSUFFICIENT, 0.0,
                              "no research evidence for a high-stakes action", True)
        return Assessment(Verdict.WEAK, 0.0, "no evidence (low-stakes, ok)", False)

    scored = [(quality_of(r), r) for r in results]
    best = max(s for s, _ in scored)
    independent = len({(r.get("provider"), (r.get("urls") or [None])[0]) for _, r in scored})

    # A contradiction among trusted sources voids count-based corroboration: you
    # cannot call two sources "agreement" if they disagree. Only relevant when the
    # decision would otherwise LEAN ON corroboration (>=2 independent, high-stakes).
    contested = False
    contested_why = ""
    if high_stakes and independent >= 2:
        contested, contested_why = _contradiction(scored, corrob, overlap_thr)

    if high_stakes and not reversible:
        if contested:
            return Assessment(Verdict.CONTESTED, best,
                              f"irreversible action but sources conflict -> resolve or escalate "
                              f"({contested_why})", True)
        if best >= strong or (best >= corrob and independent >= 2):
            return Assessment(Verdict.SUFFICIENT, best,
                              "strong or corroborated evidence for an irreversible action")
        return Assessment(Verdict.INSUFFICIENT, best,
                          "irreversible action on weak/uncorroborated research -> escalate to a "
                          "human or a stronger source", True)

    if high_stakes:
        if contested and best < adequate:
            # reversible but we were relying on corroboration and it's contradictory
            return Assessment(Verdict.CONTESTED, best,
                              f"reversible high-stakes action with conflicting sources -> review "
                              f"({contested_why})", True)
        if best >= adequate or independent >= 2:
            return Assessment(Verdict.SUFFICIENT, best, "adequate for a reversible high-stakes action")
        return Assessment(Verdict.WEAK, best, "thin evidence; proceed with caution / review")

    return Assessment(Verdict.SUFFICIENT, best, "acceptable for low-stakes exploration")


if __name__ == "__main__":
    now = datetime.now().isoformat()
    cases = [
        ("human on irreversible", [{"provider": "human", "content": "x" * 80, "ts": now}], True, False),
        ("single DDG on irreversible", [{"provider": "duckduckgo", "content": "x" * 80,
                                         "urls": ["http://random.blog"], "ts": now}], True, False),
        ("2 corroborating on irreversible", [{"provider": "brave", "content": "x" * 80,
                                              "urls": ["http://docs.python.org"], "ts": now},
                                             {"provider": "perplexity", "content": "y" * 80, "ts": now}], True, False),
        ("single DDG low-stakes", [{"provider": "duckduckgo", "content": "x" * 80, "ts": now}], False, True),
        ("wikipedia on irreversible", [{"provider": "brave", "content": "x" * 80,
                                        "urls": ["https://en.wikipedia.org/wiki/Foo"], "ts": now}], True, False),
    ]
    for label, res, hs, rev in cases:
        a = assess(res, hs, rev)
        print(f"{label:34} -> {a.verdict.value:12} ({a.score:.2f}) {'HUMAN' if a.require_human else ''}")
