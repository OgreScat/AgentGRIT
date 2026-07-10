"""
Governed Research Layer -- provider-agnostic, free-first, cost-governed, with a
legitimate human-in-the-loop path for premium research.

Cost/governance:
  1. TIER-GATED   juniors observe; managers+ may research.
  2. CACHE-FIRST  the knowledge base doubles as the cache; a repeat query is free.
  3. FREE-FIRST   cache -> DuckDuckGo (keyless) -> Brave -> Grok -> Perplexity
                  (paid only when free is empty or the task is high-stakes).
  4. BUDGET       a per-day paid-call cap; exceeding it degrades, not spends.
  5. CONDENSE     long results summarized by the LOCAL model (free) before up-tier.
  6. PROVENANCE   every result logged to logs/knowledge.jsonl (also the cache).
  7. HUMAN PATH   when premium research is warranted but no paid key is set, GRIT
                  does NOT scrape your Premium logins. It TEXTS you the query; you
                  run it in your own premium research tool and paste the answer back
                  (captured by reply_reader). Zero ToS risk, zero token cost --
                  you using your own subscription, GRIT just orchestrating.

Env: RESEARCH_ORDER, RESEARCH_MAX_PAID_PER_DAY, RESEARCH_ALLOW_HUMAN=1
The free path (cache + DuckDuckGo) needs no keys.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import date, datetime
from pathlib import Path

from src.execution.research_providers import all_providers, ResearchResult

_KB = Path(__file__).resolve().parents[2] / "logs" / "knowledge.jsonl"
_BUDGET = Path(__file__).resolve().parents[2] / "logs" / "research_budget.jsonl"
_RREQ = Path(__file__).resolve().parents[2] / "logs" / "research_requests.jsonl"

RESEARCH_TIERS = {"analyst", "manager", "developer", "gm", "grandmaster", "admin"}
_PAID = {"perplexity", "brave", "grok", "google"}  # google CSE is metered too


def _order() -> list[str]:
    # google is in the default order for consistency with brave/grok, but like
    # them it no-ops via available()=False unless its CSE keys are set, so it
    # never runs (or counts against the paid cap) for keyless users.
    raw = os.environ.get(
        "RESEARCH_ORDER", "cache,duckduckgo,brave,google,grok,perplexity"
    )
    return [x.strip() for x in raw.split(",") if x.strip()]


def _paid_today() -> int:
    if not _BUDGET.exists():
        return 0
    today = date.today().isoformat()
    n = 0
    try:
        for line in _BUDGET.read_text().splitlines():
            if line.strip() and json.loads(line).get("date") == today:
                n += 1
    except Exception:
        return 0
    return n


def _record_paid(provider: str) -> None:
    try:
        _BUDGET.parent.mkdir(parents=True, exist_ok=True)
        with _BUDGET.open("a") as f:
            f.write(json.dumps({"date": date.today().isoformat(), "provider": provider}) + "\n")
    except Exception:
        pass


def _store(result: ResearchResult) -> None:
    try:
        _KB.parent.mkdir(parents=True, exist_ok=True)
        with _KB.open("a") as f:
            f.write(json.dumps(result.to_record()) + "\n")
    except Exception:
        pass


def _condense(text: str, query: str, max_chars: int = 1200) -> str:
    """Summarize long research with the local model (free). Best-effort."""
    if len(text) <= max_chars:
        return text
    try:
        body = json.dumps({
            "model": os.environ.get("GRIT_LOCAL_MODEL", "gemma4:12b"), "think": False, "stream": False,
            "prompt": f"Summarize the following search results for the query "
                      f"'{query}' in 4-6 sentences, keeping concrete facts:\n\n{text[:6000]}",
            "options": {"num_predict": 300},
        }).encode()
        req = urllib.request.Request("http://localhost:11434/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=40) as r:
            out = json.loads(r.read()).get("response", "").strip()
        return out or text[:max_chars]
    except Exception:
        return text[:max_chars]


def request_human_research(query: str, tier: str) -> dict:
    """
    Legitimate premium research. Instead of scraping your logged-in Perplexity/Grok
    session (ToS risk) or forcing a paid API key, GRIT texts you the query. You run
    it in your own app and paste the answer back -- you, a human, using your own
    subscription. No automation, no ToS issue, no token cost. reply_reader captures
    the pasted answer and record_research_answer() caches it, so it is asked once.
    """
    try:
        from src.utils.notify import notify
    except Exception:
        return {"ok": False, "reason": "notify unavailable", "query": query}
    try:
        _RREQ.parent.mkdir(parents=True, exist_ok=True)
        with _RREQ.open("a") as f:
            f.write(json.dumps({"ts": datetime.now().isoformat(), "query": query,
                                "tier": tier, "status": "pending"}) + "\n")
    except Exception:
        pass
    notify(f'[Research · GM · AgentGRIT] Premium research needed: "{query}". '
           f"Run it in your premium research tool and reply with the answer, or reply SKIP.")
    return {"ok": False, "pending_human": True,
            "reason": "asked you to run premium research (legitimate, no ToS/cost)",
            "query": query, "tier": tier}


def record_research_answer(reply_text: str) -> dict:
    """
    Called when you paste a research answer back (via reply_reader). Matches it to
    the most recent pending research request, stores it to the knowledge base with
    source 'human' (provenance), marks the request resolved, and caches it.
    """
    if not _RREQ.exists() or not reply_text.strip():
        return {"ok": False, "reason": "no pending research request"}
    if reply_text.strip().lower() in ("skip", "no", "n"):
        return {"ok": False, "reason": "skipped by human"}
    try:
        lines = [json.loads(x) for x in _RREQ.read_text().splitlines() if x.strip()]
    except Exception:
        return {"ok": False, "reason": "cannot read requests"}
    pending = [x for x in lines if x.get("status") == "pending"]
    if not pending:
        return {"ok": False, "reason": "no pending request"}
    req = pending[-1]
    rec = {"ts": datetime.now().isoformat(), "query": req["query"], "provider": "human",
           "urls": [], "cost_estimate": 0.0, "content": reply_text.strip()}
    try:
        _KB.parent.mkdir(parents=True, exist_ok=True)
        with _KB.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        req["status"] = "resolved"
        _RREQ.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    except Exception:
        pass
    return {"ok": True, "query": req["query"], "source": "human"}


def research(query: str, tier: str = "manager", high_stakes: bool = False,
             condense: bool = True, allow_human: bool = True) -> dict:
    """Governed, provider-agnostic research. Never raises. Free path needs no keys."""
    if tier.lower() not in RESEARCH_TIERS:
        return {"ok": False, "reason": f"tier '{tier}' not permitted to research",
                "query": query, "tier": tier}

    max_paid = int(os.environ.get("RESEARCH_MAX_PAID_PER_DAY", "25"))
    providers = {p.name: p for p in all_providers()}
    tried = []

    for name in _order():
        prov = providers.get(name)
        if not prov or not prov.available():
            continue
        if name in _PAID:
            if not (high_stakes or all(t in ("cache", "duckduckgo") for t in tried)):
                continue
            if _paid_today() >= max_paid:
                tried.append(f"{name}:budget-capped")
                continue
        result = prov.search(query)
        tried.append(name)
        if result and result.content.strip():
            if name in _PAID:
                _record_paid(name)
            if condense:
                result.content = _condense(result.content, query)
            if name != "cache":
                result.ts = datetime.now().isoformat()
                _store(result)
            return {"ok": True, "provider": result.provider, "content": result.content,
                    "urls": result.urls, "query": query, "tier": tier,
                    "cost_estimate": result.cost_estimate, "tried": tried}

    # Nothing automated worked. If premium is warranted, ask the human to run it in
    # their own Premium app (legitimate) rather than scrape or force a paid key.
    if allow_human and high_stakes and os.environ.get("RESEARCH_ALLOW_HUMAN", "1") == "1":
        return request_human_research(query, tier)
    return {"ok": False, "reason": "no provider returned results (free path empty; "
            "no paid key; ask-human disabled or not high-stakes)",
            "query": query, "tier": tier, "tried": tried}


def culminate(query: str, action: str = "", high_stakes: bool = True,
              reversible: bool = False) -> dict:
    """
    The culmination pattern. GRIT does ALL the free legwork and internal review
    first, and only pings you when the evidence is genuinely too weak to act on --
    and when it does, it hands you a precise, ready-to-paste premium query, not a
    vague 'go search'.

    Flow:
      1. Run free research (no human ping).
      2. Assess quality (research_quality).
      3. SUFFICIENT -> return it; you are never bothered.
      4. INSUFFICIENT on a high-stakes/irreversible action -> compose a culmination
         prompt (what was found free + the specific gap + the exact query to run in
         your premium tool) and notify you. Your pasted answer is captured + cached.
    """
    free = research(query, tier="gm", high_stakes=high_stakes, condense=True,
                    allow_human=False)
    results = [free] if free.get("ok") else []
    try:
        from src.governance.research_quality import assess
        a = assess(results, high_stakes, reversible)
    except Exception:
        class _A:  # fail safe -> treat as insufficient
            verdict = type("V", (), {"value": "insufficient"})()
            score = 0.0
            require_human = high_stakes and not reversible
        a = _A()

    if getattr(a, "require_human", False) is False and a.verdict.value == "sufficient":
        return {"ok": True, "sufficient": True, "provider": free.get("provider"),
                "content": free.get("content"), "quality": a.score, "query": query}

    # Still weak -> culmination prompt for the human's premium tool.
    found = (free.get("content") or "nothing conclusive from free sources")[:300]
    prompt = (f"AgentGRIT reviewed free sources for: {action or query}. "
              f"Found: {found}. This is too weak to act on ({a.verdict.value}, "
              f"quality {a.score:.2f}). Please run this in your premium research tool and "
              f"paste the answer back: \"{query}\".")
    try:
        from src.utils.notify import notify
        _RREQ.parent.mkdir(parents=True, exist_ok=True)
        with _RREQ.open("a") as f:
            f.write(json.dumps({"ts": datetime.now().isoformat(), "query": query,
                                "tier": "gm", "status": "pending",
                                "culmination": True}) + "\n")
        notify(f"[Research · GM · AgentGRIT] {prompt}")
    except Exception:
        pass
    return {"ok": False, "pending_human": True, "sufficient": False,
            "verdict": a.verdict.value, "quality": a.score,
            "culmination_prompt": prompt, "query": query}


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "latest stable Python version 2026"
    r = research(q, tier="gm")
    print(f"[{'ok' if r['ok'] else 'degraded/pending'}] provider={r.get('provider','-')} "
          f"tried={r.get('tried')}")
    print((r.get("content") or r.get("reason"))[:500])
