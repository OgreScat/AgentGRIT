"""
AgentGRIT 2.0 - Two-Stage Router with Confidence Scoring

FIXES THE BRITTLENESS PROBLEM:
The old keyword-matching router was fragile. Tasks like "research the architecture
of React" contain BOTH "research" (→ Perplexity) AND "architecture" (→ Claude).

NEW APPROACH (2-Stage):
1. Stage 1: Score ALL categories with confidence levels
2. Stage 2: Policy layer picks provider based on scores + thresholds + cost

This prevents misroutes by requiring confidence thresholds before routing
to expensive providers.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import httpx


class TaskCategory(Enum):
    """Categories that determine routing."""
    SIMPLE_CODE = "simple_code"
    FORMATTING = "formatting"
    EXPLANATION = "explanation"
    RESEARCH = "research"
    DOCUMENTATION = "documentation"
    REALTIME_SOCIAL = "realtime_social"
    SOCIAL_SENTIMENT = "social_sentiment"
    COMPLEX_ARCHITECTURE = "architecture"
    SECURITY_CRITICAL = "security"
    CREATIVE = "creative"
    AMBIGUOUS = "ambiguous"


class Provider(Enum):
    """Available LLM providers in cost order."""
    OLLAMA = "ollama"           # FREE - Priority 1
    PERPLEXITY = "perplexity"   # $5/mo - Priority 2
    GROK = "grok"               # Premium - Priority 3
    CLAUDE_HAIKU = "claude-haiku"    # Cheap Claude
    CLAUDE_SONNET = "claude-sonnet"  # Medium Claude
    CLAUDE_OPUS = "claude-opus"      # Expensive - Last resort


# Cost per 1K tokens (approximate)
PROVIDER_COSTS = {
    Provider.OLLAMA: 0.0,
    Provider.PERPLEXITY: 0.001,
    Provider.GROK: 0.002,
    Provider.CLAUDE_HAIKU: 0.00025,
    Provider.CLAUDE_SONNET: 0.003,
    Provider.CLAUDE_OPUS: 0.015,
}


@dataclass
class CategoryScore:
    """Score for a single category."""
    category: TaskCategory
    score: float  # 0.0 - 1.0
    matched_signals: list[str] = field(default_factory=list)


@dataclass
class ClassificationResult:
    """Result of Stage 1 classification."""
    task: str
    scores: list[CategoryScore]
    top_category: TaskCategory
    confidence: float  # 0.0 - 1.0
    is_ambiguous: bool
    reasoning: str


@dataclass
class RoutingDecision:
    """Result of Stage 2 routing."""
    provider: Provider
    category: TaskCategory
    confidence: float
    fallback_used: bool
    cost_estimate: float
    reasoning: str


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 1: MULTI-SIGNAL CLASSIFIER
# ═══════════════════════════════════════════════════════════════════════════════

class SignalPatterns:
    """
    Signal patterns for each category.
    Each pattern has a weight (0.0-1.0) indicating strength.
    """
    
    # Simple tasks → Ollama (FREE)
    SIMPLE = {
        "keywords": [
            ("simple", 0.8), ("basic", 0.8), ("easy", 0.6),
            ("format", 0.9), ("lint", 0.9), ("indent", 0.8),
            ("comment", 0.7), ("rename", 0.7), ("import", 0.5),
            ("hello world", 1.0), ("boilerplate", 0.9),
            ("template", 0.6), ("stub", 0.7), ("scaffold", 0.6),
        ],
        "patterns": [
            (r"add\s+comments?\s+to", 0.9),
            (r"fix\s+(syntax|typo|spelling)", 0.9),
            (r"convert\s+to\s+(json|yaml|xml)", 0.8),
            (r"sort\s+(this|the)\s+(list|array)", 0.8),
        ],
        "negative": [  # Signals that reduce this score
            ("architecture", -0.5), ("design", -0.3), ("complex", -0.5),
        ],
    }
    
    # Research tasks → Perplexity (has web search)
    RESEARCH = {
        "keywords": [
            ("research", 1.0), ("search", 0.8), ("find", 0.6),
            ("lookup", 0.9), ("what is", 0.7), ("who is", 0.8),
            ("how does", 0.5), ("latest", 0.8), ("current", 0.6),
            ("documentation", 0.9), ("api docs", 1.0), ("docs for", 0.9),
            ("pypi", 1.0), ("npm", 0.9), ("github release", 0.9),
            ("competitor", 0.8), ("market", 0.6), ("pricing", 0.7),
        ],
        "patterns": [
            (r"search\s+(for|the)\s+", 0.9),
            (r"find\s+(me|the|a)\s+", 0.7),
            (r"what('s| is)\s+the\s+(latest|current)", 0.9),
            (r"look\s*up", 0.9),
        ],
        "negative": [
            ("implement", -0.3), ("code", -0.2), ("build", -0.3),
        ],
    }
    
    # Social/real-time → Grok
    SOCIAL = {
        "keywords": [
            ("twitter", 1.0), ("x.com", 1.0), ("tweet", 0.9),
            ("trending", 1.0), ("viral", 0.9), ("meme", 0.8),
            ("sentiment", 0.8),
            ("social media", 0.8), ("influencer", 0.6),
        ],
        "patterns": [
            (r"what('s| is)\s+trending", 1.0),
            (r"what\s+are\s+people\s+saying", 0.9),
        ],
        "negative": [],
    }
    
    # Complex architecture → Claude (expensive, use sparingly)
    COMPLEX = {
        "keywords": [
            ("architecture", 0.9), ("design system", 1.0), ("design pattern", 0.9),
            ("complex", 0.7), ("critical", 0.8), ("production", 0.6),
            ("refactor entire", 1.0), ("multi-file", 0.7), ("comprehensive", 0.6),
            ("security review", 1.0), ("security audit", 1.0),
            ("scalable", 0.7), ("distributed", 0.8), ("microservice", 0.7),
        ],
        "patterns": [
            (r"design\s+(the|a)\s+architecture", 1.0),
            (r"review\s+(for|the)\s+security", 1.0),
            (r"refactor\s+(the\s+)?(entire|whole)", 0.9),
            (r"how\s+should\s+(I|we)\s+(architect|design)", 0.9),
        ],
        "negative": [
            ("simple", -0.5), ("basic", -0.4), ("just", -0.2),
        ],
    }


def score_category(
    task: str,
    keywords: list[tuple[str, float]],
    patterns: list[tuple[str, float]],
    negative: list[tuple[str, float]],
) -> tuple[float, list[str]]:
    """
    Score a task against a category's signals.
    
    Returns: (score 0.0-1.0, list of matched signals)
    """
    task_lower = task.lower()
    total_score = 0.0
    max_possible = 0.0
    matched = []
    
    # Check keywords
    for keyword, weight in keywords:
        max_possible += weight
        if keyword in task_lower:
            total_score += weight
            matched.append(f"kw:{keyword}")
    
    # Check regex patterns
    for pattern, weight in patterns:
        max_possible += weight
        if re.search(pattern, task_lower):
            total_score += weight
            matched.append(f"rx:{pattern[:20]}")
    
    # Apply negative signals
    for neg_keyword, penalty in negative:
        if neg_keyword in task_lower:
            total_score += penalty  # penalty is negative
            matched.append(f"neg:{neg_keyword}")
    
    # Normalize to 0-1, saturating: ~2.0 of matched weight = full confidence.
    # Dividing by the sum of ALL signal weights (old behavior) capped every
    # task near ~0.1, below medium_confidence, so everything routed to the
    # fallback provider and cost governance never engaged (postmortem 2026-07-03).
    if max_possible > 0:
        normalized = max(0.0, min(1.0, total_score / min(max_possible, 2.0)))
    else:
        normalized = 0.0
    
    return normalized, matched


def classify_task_stage1(task: str) -> ClassificationResult:
    """
    Stage 1: Score task against all categories.
    
    Returns scores for ALL categories, not just the winner.
    This allows Stage 2 to make nuanced decisions.
    """
    scores = []
    
    # Score each category
    simple_score, simple_matched = score_category(
        task,
        SignalPatterns.SIMPLE["keywords"],
        SignalPatterns.SIMPLE["patterns"],
        SignalPatterns.SIMPLE["negative"],
    )
    scores.append(CategoryScore(TaskCategory.SIMPLE_CODE, simple_score, simple_matched))
    
    research_score, research_matched = score_category(
        task,
        SignalPatterns.RESEARCH["keywords"],
        SignalPatterns.RESEARCH["patterns"],
        SignalPatterns.RESEARCH["negative"],
    )
    scores.append(CategoryScore(TaskCategory.RESEARCH, research_score, research_matched))
    
    social_score, social_matched = score_category(
        task,
        SignalPatterns.SOCIAL["keywords"],
        SignalPatterns.SOCIAL["patterns"],
        SignalPatterns.SOCIAL["negative"],
    )
    scores.append(CategoryScore(TaskCategory.REALTIME_SOCIAL, social_score, social_matched))
    
    complex_score, complex_matched = score_category(
        task,
        SignalPatterns.COMPLEX["keywords"],
        SignalPatterns.COMPLEX["patterns"],
        SignalPatterns.COMPLEX["negative"],
    )
    scores.append(CategoryScore(TaskCategory.COMPLEX_ARCHITECTURE, complex_score, complex_matched))
    
    # Sort by score descending
    scores.sort(key=lambda x: x.score, reverse=True)
    
    top = scores[0]
    second = scores[1] if len(scores) > 1 else None
    
    # Determine if ambiguous (top two scores are close)
    is_ambiguous = False
    if second and top.score > 0 and second.score > 0:
        ratio = second.score / top.score
        is_ambiguous = ratio > 0.7  # Within 30% is ambiguous
    
    # Build reasoning
    reasoning_parts = [f"{s.category.value}:{s.score:.2f}" for s in scores[:3]]
    reasoning = f"Scores: {', '.join(reasoning_parts)}"
    if is_ambiguous:
        reasoning += f" [AMBIGUOUS: {top.category.value} vs {second.category.value}]"
    
    return ClassificationResult(
        task=task,
        scores=scores,
        top_category=top.category if top.score > 0.1 else TaskCategory.AMBIGUOUS,
        confidence=top.score,
        is_ambiguous=is_ambiguous,
        reasoning=reasoning,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# STAGE 2: POLICY-BASED ROUTING
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RoutingPolicy:
    """
    Policy configuration for routing decisions.
    """
    # Confidence thresholds
    high_confidence: float = 0.7
    medium_confidence: float = 0.4
    
    # When to allow expensive providers
    claude_min_confidence: float = 0.6  # Must be this confident to use Claude
    
    # Fallback behavior
    ambiguous_fallback: Provider = Provider.OLLAMA  # When unsure, use free
    low_confidence_fallback: Provider = Provider.PERPLEXITY  # Perplexity can handle most
    
    # Cost constraints
    avoid_claude_when_usage_above: float = 80.0  # Session percent
    
    # Category → Provider mapping (when confident)
    category_providers: dict = field(default_factory=lambda: {
        TaskCategory.SIMPLE_CODE: Provider.OLLAMA,
        TaskCategory.FORMATTING: Provider.OLLAMA,
        TaskCategory.EXPLANATION: Provider.OLLAMA,
        TaskCategory.RESEARCH: Provider.PERPLEXITY,
        TaskCategory.DOCUMENTATION: Provider.PERPLEXITY,
        TaskCategory.REALTIME_SOCIAL: Provider.GROK,
        TaskCategory.SOCIAL_SENTIMENT: Provider.GROK,
        TaskCategory.COMPLEX_ARCHITECTURE: Provider.CLAUDE_SONNET,
        TaskCategory.SECURITY_CRITICAL: Provider.CLAUDE_OPUS,
        TaskCategory.CREATIVE: Provider.CLAUDE_SONNET,
        TaskCategory.AMBIGUOUS: Provider.OLLAMA,  # When unsure, try free first
    })


def route_task_stage2(
    classification: ClassificationResult,
    policy: RoutingPolicy,
    current_claude_usage: float = 0.0,
) -> RoutingDecision:
    """
    Stage 2: Apply routing policy to classification result.
    
    Key decisions:
    1. If confidence is HIGH → use mapped provider
    2. If confidence is MEDIUM → use mapped provider but note uncertainty
    3. If confidence is LOW or AMBIGUOUS → use fallback (cheap)
    4. If Claude would be chosen but usage is high → downgrade
    """
    category = classification.top_category
    confidence = classification.confidence
    is_ambiguous = classification.is_ambiguous
    
    # Get default provider for this category
    default_provider = policy.category_providers.get(category, Provider.OLLAMA)
    
    # Decision logic
    fallback_used = False
    reasoning_parts = []
    
    # Rule 1: If ambiguous, use cheap fallback
    if is_ambiguous:
        provider = policy.ambiguous_fallback
        fallback_used = True
        reasoning_parts.append(f"Ambiguous classification → fallback to {provider.value}")
    
    # Rule 2: If low confidence, use fallback
    elif confidence < policy.medium_confidence:
        provider = policy.low_confidence_fallback
        fallback_used = True
        reasoning_parts.append(f"Low confidence ({confidence:.2f}) → fallback to {provider.value}")
    
    # Rule 3: If Claude would be chosen but we need to conserve
    elif default_provider in [Provider.CLAUDE_SONNET, Provider.CLAUDE_OPUS]:
        if current_claude_usage > policy.avoid_claude_when_usage_above:
            # Downgrade to cheaper option
            provider = Provider.PERPLEXITY if category == TaskCategory.RESEARCH else Provider.OLLAMA
            fallback_used = True
            reasoning_parts.append(
                f"Claude usage high ({current_claude_usage:.0f}%) → downgrade to {provider.value}"
            )
        elif confidence < policy.claude_min_confidence:
            # Not confident enough for expensive model
            provider = Provider.PERPLEXITY
            fallback_used = True
            reasoning_parts.append(
                f"Not confident enough for Claude ({confidence:.2f} < {policy.claude_min_confidence}) → {provider.value}"
            )
        else:
            provider = default_provider
            reasoning_parts.append(f"High confidence complex task → {provider.value}")
    
    # Rule 4: Normal routing
    else:
        provider = default_provider
        conf_level = "high" if confidence >= policy.high_confidence else "medium"
        reasoning_parts.append(f"{conf_level} confidence {category.value} → {provider.value}")
    
    # Calculate cost estimate (assuming ~500 tokens)
    estimated_tokens = 500
    cost_estimate = (estimated_tokens / 1000) * PROVIDER_COSTS.get(provider, 0.001)
    
    return RoutingDecision(
        provider=provider,
        category=category,
        confidence=confidence,
        fallback_used=fallback_used,
        cost_estimate=cost_estimate,
        reasoning=" | ".join(reasoning_parts),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# UNIFIED ROUTER CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class TwoStageRouter:
    """
    Production router that combines Stage 1 classification with Stage 2 policy.
    """
    
    def __init__(self, policy: RoutingPolicy | None = None, config: dict | None = None):
        self.policy = policy or RoutingPolicy()
        self.config = config or {}
        
        # Usage tracking
        self.claude_session_usage = 0.0
        self.requests_by_provider = {p.value: 0 for p in Provider}
        self.costs_by_provider = {p.value: 0.0 for p in Provider}
    
    def route(self, task: str) -> RoutingDecision:
        """
        Route a task through both stages.
        """
        # Stage 1: Classify
        classification = classify_task_stage1(task)
        
        # Stage 2: Route
        decision = route_task_stage2(
            classification,
            self.policy,
            self.claude_session_usage,
        )
        
        return decision
    
    async def execute(self, task: str, context: str | None = None) -> dict[str, Any]:
        """
        Route and execute a task.
        """
        decision = self.route(task)
        
        # Build prompt
        prompt = task
        if context:
            prompt = f"Context:\n{context}\n\nTask:\n{task}"
        
        # Logos Vault: validated, role-profiled reference context for the
        # local model (disabled by default; fail-closed; see docs/LOGOS-VAULT.md).
        ollama_system: str | None = None
        try:
            from src.logos_vault.context import logos_system_for
            ollama_system = logos_system_for(task) or None
        except Exception:
            ollama_system = None

        # Execute on provider
        try:
            if decision.provider == Provider.OLLAMA:
                response, tokens = await self._call_ollama(prompt, system=ollama_system)
            elif decision.provider == Provider.PERPLEXITY:
                response, tokens = await self._call_perplexity(prompt)
            elif decision.provider == Provider.GROK:
                response, tokens = await self._call_grok(prompt)
            else:
                response, tokens = await self._call_claude(prompt, decision.provider.value)
        except Exception as e:
            # On failure, try fallback
            fallback = Provider.OLLAMA
            try:
                response, tokens = await self._call_ollama(prompt, system=ollama_system)
                decision.provider = fallback
                decision.fallback_used = True
            except Exception as e2:
                return {
                    "error": str(e2),
                    "original_error": str(e),
                    "decision": decision,
                }
        
        # Track usage
        self._record_usage(decision.provider, tokens)
        
        return {
            "response": response,
            "tokens": tokens,
            "provider": decision.provider.value,
            "category": decision.category.value,
            "confidence": decision.confidence,
            "fallback_used": decision.fallback_used,
            "reasoning": decision.reasoning,
            "cost": self._calculate_cost(decision.provider, tokens),
        }
    
    def _record_usage(self, provider: Provider, tokens: int):
        """Record usage for tracking."""
        self.requests_by_provider[provider.value] += 1
        cost = self._calculate_cost(provider, tokens)
        self.costs_by_provider[provider.value] += cost
        
        # Update Claude session estimate
        if provider in [Provider.CLAUDE_HAIKU, Provider.CLAUDE_SONNET, Provider.CLAUDE_OPUS]:
            # Rough estimate: 1000 tokens ≈ 0.3% of session
            self.claude_session_usage += (tokens / 1000) * 0.3
    
    def _calculate_cost(self, provider: Provider, tokens: int) -> float:
        """Calculate cost for a request."""
        return (tokens / 1000) * PROVIDER_COSTS.get(provider, 0.001)
    
    async def _call_ollama(self, prompt: str, system: str | None = None) -> tuple[str, int]:
        """Call Ollama (FREE). Optional system prompt = Logos Vault context."""
        base_url = self.config.get("ollama_base_url", "http://localhost:11434")
        model = self.config.get("ollama_model", "gemma4:12b")
        body = {"model": model, "prompt": prompt, "stream": False}
        if system:
            body["system"] = system
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{base_url}/api/generate",
                json=body,
            )
            data = response.json()
            return data.get("response", ""), data.get("eval_count", 0)
    
    async def _call_perplexity(self, prompt: str) -> tuple[str, int]:
        """Call Perplexity (with web search)."""
        api_key = self.config.get("perplexity_api_key")
        if not api_key:
            raise ValueError("Perplexity API key not configured")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.perplexity.ai/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "llama-3.1-sonar-small-128k-online",
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens", len(content) // 4)
            return content, tokens
    
    async def _call_grok(self, prompt: str) -> tuple[str, int]:
        """Call Grok."""
        api_key = self.config.get("grok_api_key")
        if not api_key:
            raise ValueError("Grok API key not configured")
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "grok-beta",
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens", len(content) // 4)
            return content, tokens
    
    async def _call_claude(self, prompt: str, model_tier: str) -> tuple[str, int]:
        """Call Claude (use sparingly!)."""
        api_key = self.config.get("anthropic_api_key")
        if not api_key:
            raise ValueError("Anthropic API key not configured")
        
        model_map = {
            "claude-haiku": "claude-haiku-4-5-20250514",
            "claude-sonnet": "claude-sonnet-4-20250514",
            "claude-opus": "claude-opus-4-5-20250514",
        }
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": model_map.get(model_tier, model_map["claude-sonnet"]),
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            data = response.json()
            content = data["content"][0]["text"]
            tokens = data.get("usage", {}).get("input_tokens", 0) + \
                     data.get("usage", {}).get("output_tokens", 0)
            return content, tokens
    
    def get_stats(self) -> str:
        """Get usage statistics."""
        total_cost = sum(self.costs_by_provider.values())
        total_requests = sum(self.requests_by_provider.values())
        
        # Calculate savings (if everything went to Claude Opus)
        opus_cost_per_request = 0.015 * 0.5  # ~500 tokens average
        would_have_cost = total_requests * opus_cost_per_request
        savings = would_have_cost - total_cost
        
        lines = [
            "╔══════════════════════════════════════════════════════════╗",
            "║            TWO-STAGE ROUTER STATISTICS                   ║",
            "╠══════════════════════════════════════════════════════════╣",
        ]
        
        for provider in Provider:
            requests = self.requests_by_provider[provider.value]
            cost = self.costs_by_provider[provider.value]
            if requests > 0 or provider in [Provider.OLLAMA, Provider.CLAUDE_SONNET]:
                cost_str = "FREE" if provider == Provider.OLLAMA else f"${cost:.4f}"
                lines.append(f"║  {provider.value:15} │ {requests:4} requests │ {cost_str:>10} ║")
        
        lines.extend([
            "╠══════════════════════════════════════════════════════════╣",
            f"║  Total Requests:  {total_requests:4}                                  ║",
            f"║  Total Cost:      ${total_cost:.4f}                              ║",
            f"║  Claude Usage:    {self.claude_session_usage:.1f}%                               ║",
            f"║  Estimated Saved: ${savings:.4f}                              ║",
            "╚══════════════════════════════════════════════════════════╝",
        ])
        
        return "\n".join(lines)
    
    def explain_routing(self, task: str) -> str:
        """Explain how a task would be routed (for debugging)."""
        classification = classify_task_stage1(task)
        decision = route_task_stage2(classification, self.policy, self.claude_session_usage)
        
        lines = [
            f"Task: {task[:80]}...",
            "",
            "STAGE 1 - Classification:",
            f"  Top Category: {classification.top_category.value}",
            f"  Confidence: {classification.confidence:.2f}",
            f"  Ambiguous: {classification.is_ambiguous}",
            f"  Reasoning: {classification.reasoning}",
            "",
            "STAGE 2 - Routing:",
            f"  Provider: {decision.provider.value}",
            f"  Fallback Used: {decision.fallback_used}",
            f"  Cost Estimate: ${decision.cost_estimate:.4f}",
            f"  Reasoning: {decision.reasoning}",
        ]
        
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST CASES
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    router = TwoStageRouter()
    
    test_tasks = [
        # Should go to Ollama (FREE)
        "Format this Python code according to PEP8",
        "Add comments to this function",
        "Create a simple hello world script",
        
        # Should go to Perplexity (research)
        "Research the latest React 19 features",
        "Search PyPI for the latest package release notes",
        "Find the API documentation for Stripe webhooks",
        
        # Ambiguous - contains both signals
        "Research the architecture of React",  # research + architecture
        "Find and implement a design pattern",  # research + design
        
        # Should go to Grok (social)
        "What's trending on X about the new framework release?",
        "What are people saying about the new iPhone on X?",
        
        # Should go to Claude (complex) - but only if confident
        "Design the architecture for a distributed caching system",
        "Review this authentication code for security vulnerabilities",
        
        # Low signal - should fallback
        "Help me with this thing",
        "Do something with the code",
    ]
    
    print("=" * 70)
    print("TWO-STAGE ROUTER TEST CASES")
    print("=" * 70)
    
    for task in test_tasks:
        print(f"\n{router.explain_routing(task)}")
        print("-" * 70)
