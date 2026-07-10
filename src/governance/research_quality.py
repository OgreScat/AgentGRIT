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


def assess(results: list[dict], high_stakes: bool, reversible: bool) -> Assessment:
    """Is the evidence strong enough to act on, given stakes + reversibility?"""
    strong = _thr("GRIT_EVIDENCE_STRONG", 0.82)
    corrob = _thr("GRIT_EVIDENCE_CORROBORATED", 0.65)
    adequate = _thr("GRIT_EVIDENCE_ADEQUATE", 0.62)

    if not results:
        if high_stakes:
            return Assessment(Verdict.INSUFFICIENT, 0.0,
                              "no research evidence for a high-stakes action", True)
        return Assessment(Verdict.WEAK, 0.0, "no evidence (low-stakes, ok)", False)

    scored = [(quality_of(r), r) for r in results]
    best = max(s for s, _ in scored)
    independent = len({(r.get("provider"), (r.get("urls") or [None])[0]) for _, r in scored})

    if high_stakes and not reversible:
        if best >= strong or (best >= corrob and independent >= 2):
            return Assessment(Verdict.SUFFICIENT, best,
                              "strong or corroborated evidence for an irreversible action")
        return Assessment(Verdict.INSUFFICIENT, best,
                          "irreversible action on weak/uncorroborated research -> escalate to a "
                          "human or a stronger source", True)

    if high_stakes:
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
