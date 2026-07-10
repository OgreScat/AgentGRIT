"""
Pluggable research providers -- provider-agnostic, free-first.

GRIT's research muscle must not be locked to one paid API. Each provider conforms
to the same contract, so the orchestrator (research.py) can try them in cost
order: local cache -> keyless web search -> (only if configured and warranted)
paid providers. Perplexity becomes ONE optional provider, not the foundation.

Providers here:
  CacheProvider       reads logs/knowledge.jsonl for a recent hit          FREE
  DuckDuckGoProvider  keyless web search (httpx + bs4, no key, no Docker)  FREE
  PerplexityProvider  Perplexity 'sonar'  (PPLX_API_KEY)                   paid
  BraveProvider       Brave Search API    (BRAVE_API_KEY)                  paid
  GrokProvider        xAI Grok w/ web+X   (GROK_API_KEY / XAI_API_KEY)     paid

available() reports whether a provider can actually run right now (key present,
libs importable). Every provider fails safe: an error returns None, never raises.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

_KB = Path(__file__).resolve().parents[2] / "logs" / "knowledge.jsonl"


@dataclass
class ResearchResult:
    query: str
    content: str
    provider: str
    urls: list[str] = field(default_factory=list)
    ts: str = ""
    cost_estimate: float = 0.0

    def to_record(self) -> dict:
        return {"ts": self.ts or datetime.now().isoformat(), "query": self.query,
                "provider": self.provider, "urls": self.urls,
                "cost_estimate": self.cost_estimate, "content": self.content}


def _setting(name: str) -> str:
    """Read a key from src.config settings, else env. Masked callers only."""
    try:
        from src.config import settings
        v = getattr(settings, name.lower(), None)
        if v:
            return str(v)
    except Exception:
        pass
    return os.environ.get(name.upper(), "")


class ResearchProvider:
    name = "base"
    cost_per_call = 0.0

    def available(self) -> bool:
        return False

    def search(self, query: str, timeout: float = 30.0) -> ResearchResult | None:
        raise NotImplementedError


class CacheProvider(ResearchProvider):
    """Return a recent knowledge-base hit for the same query. Zero cost."""
    name = "cache"

    def __init__(self, ttl_seconds: int = 3600):
        self.ttl = ttl_seconds

    def available(self) -> bool:
        return _KB.exists()

    def search(self, query: str, timeout: float = 0) -> ResearchResult | None:
        if not _KB.exists():
            return None
        q = query.strip().lower()
        best = None
        try:
            for line in _KB.read_text().splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("query", "").strip().lower() != q:
                    continue
                age = time.time() - datetime.fromisoformat(rec["ts"]).timestamp()
                if age <= self.ttl:
                    best = rec  # keep the most recent within TTL
        except Exception:
            return None
        if best:
            return ResearchResult(query=query, content=best.get("content", ""),
                                  provider="cache", urls=best.get("urls", []),
                                  ts=best.get("ts", ""))
        return None


class DuckDuckGoProvider(ResearchProvider):
    """Keyless web search via DuckDuckGo's HTML endpoint. Free, no dependency
    beyond httpx + bs4 (already installed). Best-effort; fails safe to None."""
    name = "duckduckgo"

    def available(self) -> bool:
        try:
            import bs4  # noqa: F401
            import httpx  # noqa: F401
            return True
        except Exception:
            return False

    def search(self, query: str, timeout: float = 20.0) -> ResearchResult | None:
        try:
            import httpx
            from bs4 import BeautifulSoup
        except Exception:
            return None
        try:
            r = httpx.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (research; AgentGRIT)"},
                timeout=timeout, follow_redirects=True,
            )
            soup = BeautifulSoup(r.text, "html.parser")
            hits, urls = [], []
            for res in soup.select(".result__body")[:5]:
                a = res.select_one(".result__a")
                snip = res.select_one(".result__snippet")
                if a:
                    urls.append(a.get("href", ""))
                    hits.append(f"- {a.get_text(strip=True)}: "
                                f"{snip.get_text(strip=True) if snip else ''}")
            if not hits:
                return None
            return ResearchResult(query=query, content="\n".join(hits),
                                  provider="duckduckgo", urls=urls)
        except Exception:
            return None


class PerplexityProvider(ResearchProvider):
    name = "perplexity"
    cost_per_call = 0.005

    def available(self) -> bool:
        return bool(_setting("PPLX_API_KEY"))

    def search(self, query: str, timeout: float = 40.0) -> ResearchResult | None:
        key = _setting("PPLX_API_KEY")
        if not key:
            return None
        body = json.dumps({"model": "sonar",
                           "messages": [{"role": "user", "content": query}]}).encode()
        req = urllib.request.Request(
            "https://api.perplexity.ai/chat/completions", data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
            return ResearchResult(query=query,
                                  content=data["choices"][0]["message"]["content"],
                                  provider="perplexity", cost_estimate=self.cost_per_call)
        except Exception:
            return None


class BraveProvider(ResearchProvider):
    name = "brave"
    cost_per_call = 0.005

    def available(self) -> bool:
        return bool(_setting("BRAVE_API_KEY"))

    def search(self, query: str, timeout: float = 20.0) -> ResearchResult | None:
        key = _setting("BRAVE_API_KEY")
        if not key:
            return None
        url = "https://api.search.brave.com/res/v1/web/search?q=" + urllib.parse.quote(query)
        req = urllib.request.Request(url, headers={"X-Subscription-Token": key,
                                                   "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
            results = data.get("web", {}).get("results", [])[:5]
            hits = [f"- {r.get('title', '')}: {r.get('description', '')}" for r in results]
            urls = [r.get("url", "") for r in results]
            return ResearchResult(query=query, content="\n".join(hits),
                                  provider="brave", urls=urls,
                                  cost_estimate=self.cost_per_call)
        except Exception:
            return None


class GrokProvider(ResearchProvider):
    """xAI Grok with native web + X search. Ready when a key is present."""
    name = "grok"
    cost_per_call = 0.01

    def available(self) -> bool:
        return bool(_setting("GROK_API_KEY") or _setting("XAI_API_KEY"))

    def search(self, query: str, timeout: float = 45.0) -> ResearchResult | None:
        key = _setting("GROK_API_KEY") or _setting("XAI_API_KEY")
        if not key:
            return None
        body = json.dumps({"model": "grok-4",
                           "messages": [{"role": "user", "content": query}]}).encode()
        req = urllib.request.Request(
            "https://api.x.ai/v1/chat/completions", data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
            return ResearchResult(query=query,
                                  content=data["choices"][0]["message"]["content"],
                                  provider="grok", cost_estimate=self.cost_per_call)
        except Exception:
            return None


class BrowserSessionProvider(ResearchProvider):
    """OPT-IN, DISABLED BY DEFAULT. Would drive your logged-in Perplexity/Grok
    Premium web session via browser automation to avoid API fees.

    GRIT deliberately does NOT implement this: automating a consumer web login
    almost certainly violates the provider ToS and risks your account being
    flagged or banned (a Zeroth-Law foreseeable harm to your interests). It is
    also fragile. Use Brave's free API tier or DuckDuckGo instead; use real API
    keys when you want premium synthesis and accept the metered cost.

    If you ever explicitly opt in (RESEARCH_ALLOW_SESSION_SCRAPE=1) you accept the
    ToS/account risk and implement the automation yourself behind this stub."""
    name = "browser_session"

    def available(self) -> bool:
        return os.environ.get("RESEARCH_ALLOW_SESSION_SCRAPE") == "1"

    def search(self, query: str, timeout: float = 45.0) -> ResearchResult | None:
        if not self.available():
            return None
        raise NotImplementedError(
            "Session scraping is opt-in and unimplemented by design. Automating a "
            "Premium web login likely violates provider ToS and risks your account. "
            "Prefer Brave free tier / DuckDuckGo, or use an API key. See "
            "docs/RESEARCH-KEYLESS.md.")


class GoogleProvider(ResearchProvider):
    """Google Custom Search JSON API — broad index, mid-trust (tier 0.72).

    Requires GOOGLE_CSE_API_KEY and GOOGLE_CSE_ID (create at cse.google.com).
    Free tier: 100 queries/day; paid: ~$5 per 1,000 queries.
    Breadth is the value; known ranking/filtering bias on some topics is why
    the trust tier sits below Perplexity/Grok — a lone Google result cannot
    authorize an irreversible action (see research_quality.py).
    """

    name = "google"
    cost_per_call = 0.005

    def available(self) -> bool:
        return bool(_setting("GOOGLE_CSE_API_KEY") and _setting("GOOGLE_CSE_ID"))

    def search(self, query: str, timeout: float = 30.0) -> ResearchResult | None:
        api_key = _setting("GOOGLE_CSE_API_KEY")
        cse_id = _setting("GOOGLE_CSE_ID")
        if not api_key or not cse_id:
            return None
        try:
            url = (
                "https://www.googleapis.com/customsearch/v1"
                f"?key={urllib.parse.quote(api_key)}&cx={urllib.parse.quote(cse_id)}"
                f"&q={urllib.parse.quote(query)}&num=5"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "AgentGRIT/2.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
            items = data.get("items", [])
            if not items:
                return None
            content = "\n\n".join(
                f"{it.get('title', '')}: {it.get('snippet', '')}" for it in items[:5]
            )
            urls = [it.get("link", "") for it in items[:5]]
            return ResearchResult(query=query, content=content, provider=self.name,
                                  urls=urls, cost_estimate=self.cost_per_call)
        except Exception:
            return None


# Cost-ordered registry: free providers first.
def all_providers() -> list[ResearchProvider]:
    return [CacheProvider(), DuckDuckGoProvider(),
            PerplexityProvider(), BraveProvider(),
            GoogleProvider(), GrokProvider()]
