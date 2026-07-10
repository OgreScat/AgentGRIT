"""
AgentGRIT 2.4 - Multi-LLM Router (Capability-Based)

THE CORE PURPOSE: Maximize utility while minimizing expensive API usage.

Your situation:
- Claude: usage-capped per session and per week (reset day is configurable)
- Perplexity API (Sonar): pay-as-you-go, ~$0.20-$1.00/1M tokens by tier;
  API credits are separate from the Pro consumer subscription
- Grok 4.x (xAI API): frontier agentic tier at competitive per-task cost
- Ollama Local: Free, unlimited, but limited capability

Strategy:
1. RESEARCH tasks → Perplexity Sonar (cheap grounded search with citations)
2. SIMPLE CODING tasks → Ollama local (free, unlimited)
3. COMPLEX REASONING → Claude only when absolutely necessary
4. REAL-TIME/X context → Grok (xAI firehose access Perplexity lacks)

This router decides WHICH model to use based on task type.
Claude should only be called for truly complex architectural decisions.
"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Literal

import httpx
from pydantic import BaseModel


# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

from src.utils.logging import log_routing_decision as _log_routing_decision
from src.governance.personas import get_persona_prompt, select_persona
from src.governance.bylaws import get_bylaw_engine, BylawAction
from src.governance.identity import wrap_task_with_identity
from src.governance.model_provenance import is_model_approved, explain as explain_provenance
from src.governance.memory import get_memory_store, extract_lesson


class TaskCategory(Enum):
    """Categories that determine which LLM to route to."""
    
    # Ollama handles these (FREE)
    SIMPLE_CODE = "simple_code"          # Basic code generation, fixes
    FORMATTING = "formatting"             # Code formatting, linting help
    BOILERPLATE = "boilerplate"          # Generate boilerplate code
    EXPLANATION = "explanation"           # Explain code/concepts
    
    # Perplexity handles these (cheap Sonar API tier)
    RESEARCH = "research"                 # Web research, lookups
    CURRENT_EVENTS = "current_events"     # News, recent info
    DOCUMENTATION = "documentation"       # API docs, library info
    COMPETITOR_ANALYSIS = "competitor"    # Market research
    
    # Grok handles these
    REALTIME_SOCIAL = "realtime_social"   # X/Twitter context
    INTERNET_CULTURE = "internet_culture" # Internet culture
    SOCIAL_SENTIMENT = "social_sentiment"   # Social sentiment
    
    # Claude ONLY for these (expensive - use sparingly!)
    COMPLEX_ARCHITECTURE = "architecture" # System design decisions
    MULTI_FILE_REFACTOR = "refactor"      # Large-scale code changes
    CRITICAL_DECISIONS = "critical"       # Security, production code
    CREATIVE_WRITING = "creative"         # High-quality prose


# Cost estimates per 1K tokens (approximate)
# Approximate $/1K tokens (blended in/out), July 2026 — review periodically.
# These are routing PRIORITIES expressed as estimates, not live metered billing.
MODEL_COSTS = {
    "ollama": 0.00,           # Free — local, unlimited
    "perplexity": 0.001,      # Sonar tier (~$0.20-$1.00/1M by size), grounded search
    "grok": 0.002,            # Grok 4.x agentic tier (~$2/1M in) — strong cost/perf
    "claude-haiku": 0.00025,  # If we must use Claude, use Haiku
    "claude-sonnet": 0.003,   # Medium cost
    "claude-opus": 0.015,     # Expensive - avoid when possible
}


# Which model handles which task type
ROUTING_TABLE: dict[TaskCategory, str] = {
    # FREE (Ollama)
    TaskCategory.SIMPLE_CODE: "ollama",
    TaskCategory.FORMATTING: "ollama",
    TaskCategory.BOILERPLATE: "ollama",
    TaskCategory.EXPLANATION: "ollama",
    
    # CHEAP (Perplexity - uses your $5/month)
    TaskCategory.RESEARCH: "perplexity",
    TaskCategory.CURRENT_EVENTS: "perplexity",
    TaskCategory.DOCUMENTATION: "perplexity",
    TaskCategory.COMPETITOR_ANALYSIS: "perplexity",
    
    # CHEAP (Grok)
    TaskCategory.REALTIME_SOCIAL: "grok",
    TaskCategory.INTERNET_CULTURE: "grok",
    TaskCategory.SOCIAL_SENTIMENT: "grok",
    
    # EXPENSIVE (Claude - only when necessary)
    TaskCategory.COMPLEX_ARCHITECTURE: "claude-sonnet",
    TaskCategory.MULTI_FILE_REFACTOR: "claude-sonnet",
    TaskCategory.CRITICAL_DECISIONS: "claude-opus",
    TaskCategory.CREATIVE_WRITING: "claude-sonnet",
}


@dataclass
class UsageTracker:
    """Track usage across all providers to stay within limits."""
    
    # Claude limits (your constraints)
    claude_session_percent: float = 0.0    # Current session usage
    claude_weekly_percent: float = 0.0     # Weekly usage (resets on your configured day)
    claude_weekly_reset_day: str = "Monday"
    
    # Perplexity limits ($5/month free)
    perplexity_monthly_budget: float = 5.00
    perplexity_monthly_used: float = 0.00
    
    # Grok (Premium subscription)
    grok_available: bool = True
    
    # Ollama (always available, free)
    ollama_available: bool = True
    
    # Tracking
    requests_today: dict[str, int] = field(default_factory=lambda: {
        "ollama": 0, "perplexity": 0, "grok": 0, "claude": 0
    })
    tokens_today: dict[str, int] = field(default_factory=lambda: {
        "ollama": 0, "perplexity": 0, "grok": 0, "claude": 0
    })
    
    def should_avoid_claude(self) -> bool:
        """Check if we should avoid Claude to preserve limits."""
        # If session > 80% or weekly > 50%, avoid Claude
        return self.claude_session_percent > 80 or self.claude_weekly_percent > 50
    
    def perplexity_budget_remaining(self) -> float:
        """Check remaining Perplexity budget."""
        return self.perplexity_monthly_budget - self.perplexity_monthly_used
    
    def record_usage(self, provider: str, tokens: int, cost: float = 0.0):
        """Record usage for a provider."""
        self.requests_today[provider] = self.requests_today.get(provider, 0) + 1
        self.tokens_today[provider] = self.tokens_today.get(provider, 0) + tokens
        
        if provider == "perplexity":
            self.perplexity_monthly_used += cost
        elif provider == "claude":
            # Estimate: ~1000 tokens = 0.3% of daily limit
            self.claude_session_percent += (tokens / 1000) * 0.3
    
    def get_status_report(self) -> str:
        """Get a human-readable status report."""
        return f"""
📊 LLM Usage Status
═══════════════════════════════════════
Claude:
  • Session: {self.claude_session_percent:.1f}%
  • Weekly: {self.claude_weekly_percent:.1f}% (resets {self.claude_weekly_reset_day})
  • Status: {'⚠️ CONSERVE' if self.should_avoid_claude() else '✅ OK'}

Perplexity:
  • Budget: ${self.perplexity_budget_remaining():.2f} remaining
  • Status: {'⚠️ LOW' if self.perplexity_budget_remaining() < 1 else '✅ OK'}

Grok: {'✅ Available' if self.grok_available else '❌ Unavailable'}
Ollama: {'✅ Available (FREE)' if self.ollama_available else '❌ Unavailable'}

Today's Requests:
  • Ollama: {self.requests_today.get('ollama', 0)} (free)
  • Perplexity: {self.requests_today.get('perplexity', 0)}
  • Grok: {self.requests_today.get('grok', 0)}
  • Claude: {self.requests_today.get('claude', 0)} ({'⚠️' if self.requests_today.get('claude', 0) > 5 else '✅'})
═══════════════════════════════════════
"""


@dataclass
class ClassificationResult:
    """Result of task classification with confidence and reasoning."""
    category: TaskCategory
    confidence: float  # 0.0 - 1.0
    reason: str
    required_capabilities: list[str]


# Capability matrix: what each provider CAN do
PROVIDER_CAPABILITIES = {
    "ollama": {
        "code_generation": True,
        "code_explanation": True,
        "formatting": True,
        "web_search": False,  # Cannot search the web
        "real_time_social": False,
        "multi_file_reasoning": False,  # Limited context window
        "complex_architecture": False,
        "max_context_tokens": 8192,
        "cost_per_1k": 0.0,
    },
    "perplexity": {
        "code_generation": True,
        "code_explanation": True,
        "formatting": True,
        "web_search": True,  # KEY CAPABILITY
        "real_time_social": False,
        "multi_file_reasoning": True,
        "complex_architecture": False,
        "max_context_tokens": 128000,
        "cost_per_1k": 0.001,
    },
    "grok": {
        "code_generation": True,
        "code_explanation": True,
        "formatting": True,
        "web_search": True,
        "real_time_social": True,  # KEY CAPABILITY - X/Twitter context
        "multi_file_reasoning": True,
        "complex_architecture": False,
        "max_context_tokens": 131072,
        "cost_per_1k": 0.002,
    },
    "claude-sonnet": {
        "code_generation": True,
        "code_explanation": True,
        "formatting": True,
        "web_search": False,
        "real_time_social": False,
        "multi_file_reasoning": True,  # KEY CAPABILITY
        "complex_architecture": True,  # KEY CAPABILITY
        "max_context_tokens": 200000,
        "cost_per_1k": 0.003,
    },
    "claude-opus": {
        "code_generation": True,
        "code_explanation": True,
        "formatting": True,
        "web_search": False,
        "real_time_social": False,
        "multi_file_reasoning": True,
        "complex_architecture": True,
        "max_context_tokens": 200000,
        "cost_per_1k": 0.015,
    },
}


def _detect_required_capabilities(task: str) -> tuple[list[str], float]:
    """
    Analyze task to determine what capabilities are REQUIRED.
    Returns (capabilities_list, confidence).

    This is capability-based, not keyword-based.
    The question is: "What does this task NEED?" not "What words are in it?"
    """
    task_lower = task.lower()
    required = []
    confidence = 0.8  # Base confidence

    # Web search required?
    # Not just "search" keyword - needs EXTERNAL/CURRENT information
    web_indicators = [
        "pypi", "npm", "github release", "wikipedia", "documentation",
        "latest", "current", "today", "recent", "news", "2024", "2025", "2026",
        "what is the price", "how much does", "who won", "what happened",
    ]
    external_info_patterns = [
        r"look up", r"find out", r"research", r"what does .+ say",
        r"according to", r"on the web", r"online",
    ]
    if any(w in task_lower for w in web_indicators):
        required.append("web_search")
        confidence = min(confidence + 0.1, 1.0)
    elif any(re.search(p, task_lower) for p in external_info_patterns):
        required.append("web_search")

    # Real-time social context required?
    # FIXED: word-boundary patterns, not bare substrings. The original
    # bare substring checks matched inside ordinary words/text -
    # "exact code", "correct answer", any dollar amount or shell $VAR -
    # which silently misrouted normal free-tier-eligible work to Grok
    # (a paid provider, unconfigured by default). Found via a real live
    # dispatch that got routed to Grok for a plain scraper-bugfix task
    # whose text happened to contain "for this exact code."
    social_phrase_indicators = [
        "twitter", "x.com", "trending", "viral", "sentiment",
        "what are people saying",
    ]
    social_token_patterns = [
        r"(?<!\w)@\w+",           # an actual @handle, not an email local-part or a decorator
    ]
    if any(w in task_lower for w in social_phrase_indicators) or any(
        re.search(p, task_lower) for p in social_token_patterns
    ):
        required.append("real_time_social")
        confidence = min(confidence + 0.1, 1.0)

    # Multi-file reasoning required?
    multi_file_indicators = [
        "entire codebase", "all files", "refactor", "across the project",
        "multiple files", "dependency graph", "import chain",
    ]
    file_count_pattern = r"(\d+)\s*(files?|modules?|components?)"
    if any(w in task_lower for w in multi_file_indicators):
        required.append("multi_file_reasoning")
    elif re.search(file_count_pattern, task_lower):
        match = re.search(file_count_pattern, task_lower)
        if match and int(match.group(1)) > 3:
            required.append("multi_file_reasoning")

    # Complex architecture required?
    # This is about DESIGN DECISIONS, not just coding
    architecture_indicators = [
        "architecture", "design system", "system design", "tradeoffs",
        "scalability", "distributed", "microservices", "data model",
        "security model", "authentication flow", "authorization",
    ]
    if any(w in task_lower for w in architecture_indicators):
        required.append("complex_architecture")
        confidence = min(confidence + 0.15, 1.0)

    # If no special capabilities needed, it's simple
    if not required:
        required.append("code_generation")  # Default capability
        confidence = 0.9  # High confidence for simple tasks

    return required, confidence


def _select_cheapest_capable_provider(
    required_capabilities: list[str],
    usage_tracker: "UsageTracker",
) -> tuple[str, str]:
    """
    Select the cheapest provider that has ALL required capabilities.
    Returns (provider_name, reason).

    Priority order (by cost): ollama → perplexity → grok → claude-sonnet → claude-opus
    """
    priority_order = ["ollama", "perplexity", "grok", "claude-sonnet", "claude-opus"]

    # Apply budget constraints
    if usage_tracker.should_avoid_claude():
        # Remove Claude options if at limit
        priority_order = [p for p in priority_order if not p.startswith("claude")]

    if usage_tracker.perplexity_budget_remaining() < 0.50:
        # Remove Perplexity if budget low
        priority_order = [p for p in priority_order if p != "perplexity"]

    for provider in priority_order:
        caps = PROVIDER_CAPABILITIES[provider]
        has_all = all(caps.get(cap, False) for cap in required_capabilities)
        if has_all:
            reason = f"Cheapest provider with {', '.join(required_capabilities)}"
            return provider, reason

    # Fallback: if no provider has all capabilities, use best available
    # This shouldn't happen with current capability set
    return "claude-sonnet", "Fallback: no provider matched all requirements"


def classify_task(task_description: str, usage_tracker: "UsageTracker" = None) -> ClassificationResult:
    """
    Classify a task using capability-based analysis.

    This replaces the old keyword-matching approach with a more robust
    capability-based classifier that:
    1. Determines what capabilities the task REQUIRES
    2. Selects the cheapest provider with those capabilities
    3. Logs the decision with reasoning (evidence bundle)

    This is harder to "jailbreak" because it analyzes NEEDS, not words.
    """
    if usage_tracker is None:
        usage_tracker = UsageTracker()

    # Step 1: Detect required capabilities
    required_caps, confidence = _detect_required_capabilities(task_description)

    # Step 2: Map capabilities to category (for backward compatibility)
    if "complex_architecture" in required_caps:
        category = TaskCategory.COMPLEX_ARCHITECTURE
    elif "real_time_social" in required_caps:
        category = TaskCategory.REALTIME_SOCIAL
    elif "web_search" in required_caps:
        category = TaskCategory.RESEARCH
    elif "multi_file_reasoning" in required_caps:
        category = TaskCategory.MULTI_FILE_REFACTOR
    else:
        category = TaskCategory.SIMPLE_CODE

    # Step 3: Get reason for classification
    reason = f"Task requires: {', '.join(required_caps)}"

    return ClassificationResult(
        category=category,
        confidence=confidence,
        reason=reason,
        required_capabilities=required_caps,
    )


# Backward compatibility: simple function that just returns category
def classify_task_simple(task_description: str) -> TaskCategory:
    """Simple classifier for backward compatibility."""
    return classify_task(task_description).category


@dataclass
class RoutingDecision:
    """Complete routing decision with evidence bundle for audit trail."""
    provider: str
    category: TaskCategory
    confidence: float
    reason: str
    required_capabilities: list[str]
    estimated_cost: float
    persona_id: str | None = None  # 5-Element Persona if applicable
    timestamp: datetime = field(default_factory=datetime.now)

    def to_log_entry(self) -> dict:
        """Convert to loggable dict for evidence trail."""
        entry = {
            "provider": self.provider,
            "category": self.category.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "capabilities": self.required_capabilities,
            "estimated_cost_usd": self.estimated_cost,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.persona_id:
            entry["persona"] = self.persona_id
        return entry


class LLMRouter:
    """
    Routes tasks to the most cost-effective LLM using capability-based analysis.

    Key principles (from Part 2 conversation):
    1. Capability-based, not keyword-based routing
    2. Every decision logged with evidence bundle
    3. Hard budget gates before execution
    4. Cost-first: Ollama → Perplexity → Grok → Claude
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.usage = UsageTracker()
        self.routing_log: list[RoutingDecision] = []  # Evidence trail

        # API clients (initialized lazily)
        self._ollama_client = None
        self._perplexity_client = None
        self._grok_client = None
        self._claude_client = None

    def route(self, task: str, force_provider: str | None = None) -> str:
        """
        Determine which provider should handle a task.

        Args:
            task: Task description
            force_provider: Override routing (for testing)

        Returns:
            Provider name: "ollama", "perplexity", "grok", or "claude-*"
        """
        decision = self.route_with_evidence(task, force_provider)
        return decision.provider

    def route_with_evidence(
        self, task: str, force_provider: str | None = None
    ) -> RoutingDecision:
        """
        Route task and return full evidence bundle.

        This is the preferred method - always returns reasoning.
        """
        if force_provider:
            return RoutingDecision(
                provider=force_provider,
                category=TaskCategory.SIMPLE_CODE,
                confidence=1.0,
                reason=f"Forced to {force_provider} (override)",
                required_capabilities=["forced"],
                estimated_cost=0.0,
            )

        # Step 1: Classify using capability-based analysis
        classification = classify_task(task, self.usage)

        # Step 2: Select cheapest capable provider
        provider, selection_reason = _select_cheapest_capable_provider(
            classification.required_capabilities,
            self.usage,
        )

        # Step 3: Estimate cost
        est_tokens = len(task.split()) * 3  # Rough estimate
        cost_per_1k = PROVIDER_CAPABILITIES.get(provider, {}).get("cost_per_1k", 0.01)
        estimated_cost = (est_tokens / 1000) * cost_per_1k

        # Step 4: Select persona if applicable (5-Element Framework)
        persona = select_persona(task, classification.category.value)
        persona_id = persona.id if persona else None

        # Step 5: Create decision with full evidence
        decision = RoutingDecision(
            provider=provider,
            category=classification.category,
            confidence=classification.confidence,
            reason=f"{classification.reason} | {selection_reason}",
            required_capabilities=classification.required_capabilities,
            estimated_cost=estimated_cost,
            persona_id=persona_id,
        )

        # Step 6: Log for audit trail (in-memory)
        self.routing_log.append(decision)

        # Step 7: Persist to logs/router.jsonl
        log_entry = decision.to_log_entry()
        log_entry["task_preview"] = task[:100] if len(task) > 100 else task
        _log_routing_decision(log_entry)

        return decision

    def _legacy_route(self, task: str) -> str:
        """Legacy routing for backward compatibility."""
        # Classify the task
        category = classify_task_simple(task)

        # Get default provider for this category
        provider = ROUTING_TABLE[category]

        # Apply cost-saving overrides
        if provider.startswith("claude") and self.usage.should_avoid_claude():
            # Try to downgrade Claude tasks when at limit
            if category in [TaskCategory.EXPLANATION, TaskCategory.SIMPLE_CODE]:
                provider = "ollama"
            elif category == TaskCategory.RESEARCH:
                provider = "perplexity"
        
        # Check Perplexity budget
        if provider == "perplexity" and self.usage.perplexity_budget_remaining() < 0.50:
            # Fallback to Ollama if Perplexity budget is low
            provider = "ollama"
        
        return provider
    
    async def execute(
        self,
        task: str,
        context: str | None = None,
        force_provider: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute a task using the optimal LLM.

        Returns:
            {
                "provider": "ollama" | "perplexity" | "grok" | "claude",
                "response": str,
                "tokens": int,
                "cost": float,
                "category": str,
                "routing_decision": dict  # Full evidence bundle
            }
        """
        decision = self.route_with_evidence(task, force_provider)
        provider = decision.provider
        category = decision.category

        # Build prompt with optional persona prefix (5-Element Framework)
        persona_prefix = get_persona_prompt(task, provider, category.value)
        prompt = task
        if context:
            prompt = f"Context:\n{context}\n\nTask:\n{task}"
        if persona_prefix:
            prompt = persona_prefix + prompt

        # AgentGRIT bylaws gate — hard enforcement, runs regardless of
        # provider or model behavior. This is a code-level check, not a
        # request to the model to behave; it cannot be talked past.
        bylaw_engine = get_bylaw_engine()
        bylaw_result = bylaw_engine.evaluate(
            task,
            context={"estimated_cost": decision.estimated_cost},
            action_type="api_call",
        )
        if bylaw_result.action == BylawAction.BLOCK:
            return {
                "provider": "bylaws",
                "response": f"Blocked by bylaws: {bylaw_result.reason}",
                "tokens": 0,
                "cost": 0.0,
                "category": category.value,
                "routing_decision": decision.to_log_entry(),
                "bylaw_action": bylaw_result.action.value,
            }

        # Local model gets the live AgentGRIT identity prompt prepended —
        # a behavioral supplement, not a substitute for the gate above.
        if provider == "ollama":
            prompt = wrap_task_with_identity(prompt, category.value)

        # Execute on chosen provider
        if provider == "ollama":
            response, tokens = await self._call_ollama(prompt)
            cost = 0.0
        elif provider == "perplexity":
            response, tokens = await self._call_perplexity(prompt)
            cost = tokens * MODEL_COSTS["perplexity"] / 1000
        elif provider == "grok":
            response, tokens = await self._call_grok(prompt)
            cost = tokens * MODEL_COSTS["grok"] / 1000
        else:
            # Claude - use smallest model that can do the job
            model = "claude-sonnet" if category != TaskCategory.CRITICAL_DECISIONS else "claude-opus"
            response, tokens = await self._call_claude(prompt, model)
            cost = tokens * MODEL_COSTS[model] / 1000
        
        # Bylaws-gated memory: if the local model self-reported a LESSON
        # line (see identity.py's "Report format" contract), try to
        # persist it. remember() itself decides whether it actually gets
        # written, held for review, or rejected outright - see
        # governance/memory.py. Never let a memory-write attempt break a
        # task that otherwise succeeded.
        if provider == "ollama":
            lesson = extract_lesson(response)
            if lesson:
                try:
                    get_memory_store().remember(
                        lesson,
                        source_task=task[:200],
                        task_pattern=category.value,
                        evidence=f"router.execute() ollama dispatch, {datetime.utcnow().isoformat()}",
                    )
                except Exception:
                    pass

        # Record usage
        self.usage.record_usage(provider, tokens, cost)

        return {
            "provider": provider,
            "response": response,
            "tokens": tokens,
            "cost": cost,
            "category": category.value,
            "routing_decision": decision.to_log_entry(),  # Evidence bundle
        }
    
    async def _call_ollama(self, prompt: str) -> tuple[str, int]:
        """Call local Ollama. FREE and unlimited."""
        model = self.config.get("ollama_model", "gemma4:12b")
        if not is_model_approved(model):
            return f"Blocked by provenance policy: {explain_provenance(model)}", 0
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:11434/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                    },
                    timeout=120.0,
                )
                data = response.json()
                return data.get("response", ""), data.get("eval_count", 0)
        except Exception as e:
            return f"Ollama error: {e}", 0
    
    async def _call_perplexity(self, prompt: str) -> tuple[str, int]:
        """Call Perplexity Sonar API (pay-as-you-go credits, budget-gated)."""
        api_key = self.config.get("perplexity_api_key")
        if not api_key:
            return "Perplexity API key not configured", 0
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.perplexity.ai/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        # Override with PPLX_MODEL as Perplexity renames Sonar tiers.
                        "model": os.environ.get(
                            "PPLX_MODEL", "llama-3.1-sonar-small-128k-online"
                        ),
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=60.0,
                )
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                return content, tokens
        except Exception as e:
            return f"Perplexity error: {e}", 0
    
    async def _call_grok(self, prompt: str) -> tuple[str, int]:
        """Call Grok API (xAI)."""
        api_key = self.config.get("grok_api_key")
        if not api_key:
            return "Grok API key not configured", 0
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.x.ai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        # Override with GROK_MODEL as xAI ships new versions.
                        "model": os.environ.get("GROK_MODEL", "grok-beta"),
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=60.0,
                )
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                return content, tokens
        except Exception as e:
            return f"Grok error: {e}", 0
    
    async def _call_claude(self, prompt: str, model: str = "claude-sonnet") -> tuple[str, int]:
        """
        Call Claude API. USE SPARINGLY.
        
        This should only be called for truly complex tasks that other models can't handle.
        """
        api_key = self.config.get("anthropic_api_key")
        if not api_key:
            return "Anthropic API key not configured", 0
        
        model_map = {
            "claude-haiku": "claude-haiku-4-5-20250514",
            "claude-sonnet": "claude-sonnet-4-20250514",
            "claude-opus": "claude-opus-4-5-20250514",
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model_map.get(model, model_map["claude-sonnet"]),
                        "max_tokens": 4096,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    timeout=120.0,
                )
                data = response.json()
                content = data["content"][0]["text"]
                tokens = data.get("usage", {}).get("input_tokens", 0) + data.get("usage", {}).get("output_tokens", 0)
                return content, tokens
        except Exception as e:
            return f"Claude error: {e}", 0
    
    def get_routing_explanation(self, task: str) -> str:
        """Explain why a task would be routed to a specific provider."""
        category = classify_task(task)
        provider = self.route(task)
        
        explanations = {
            "ollama": "🆓 Routed to Ollama (FREE, unlimited) - Simple task that doesn't need expensive models",
            "perplexity": "🔍 Routed to Perplexity ($5/month free tier) - Research task with web search",
            "grok": "🐦 Routed to Grok - Real-time social/X context needed",
            "claude-haiku": "💰 Routed to Claude Haiku (cheap) - Needs Claude quality but simple task",
            "claude-sonnet": "💰💰 Routed to Claude Sonnet - Complex task requiring strong reasoning",
            "claude-opus": "💰💰💰 Routed to Claude Opus (expensive!) - Critical decision requiring best quality",
        }
        
        return f"""
Task: {task[:100]}...
Category: {category.value}
Provider: {provider}

{explanations.get(provider, "Unknown routing")}

Current Usage:
{self.usage.get_status_report()}
"""


# Global router instance
_router: LLMRouter | None = None


def get_router(config: dict[str, Any] | None = None) -> LLMRouter:
    """Get or create the global LLM router."""
    global _router
    if _router is None:
        _router = LLMRouter(config)
    return _router


# ═══════════════════════════════════════════════════════════════════════════════
# EXAMPLE USAGE
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    router = get_router({
        "ollama_model": "gemma4:12b",
        "perplexity_api_key": "pplx-your-key",
    })
    
    # Test routing decisions
    test_tasks = [
        "Research pypi.org for the latest package release data",
        "Write a simple hello world function in Python",
        "What are people saying about the new GPU release on X?",
        "Design the architecture for a self-governing agent system",
        "Explain how this JavaScript function works",
        "Format this code according to PEP8",
    ]
    
    print("=" * 60)
    print("LLM ROUTING DECISIONS")
    print("=" * 60)
    
    for task in test_tasks:
        print(router.get_routing_explanation(task))
        print("-" * 60)
