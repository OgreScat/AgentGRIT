"""
AgentGRIT Execution Layer

Handles AI model interactions with:
- Primary: Anthropic Claude API
- Secondary: Perplexity Pro (for research)
- Fallback: Local Ollama (for offline/cost-sensitive)
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncGenerator

import httpx
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import settings


class ModelProvider(Enum):
    """Available model providers."""
    
    ANTHROPIC = "anthropic"
    PERPLEXITY = "perplexity"
    OLLAMA = "ollama"


class ModelTier(Enum):
    """Model tiers for task complexity."""
    
    SIMPLE = "simple"      # Quick tasks, cheap
    STANDARD = "standard"  # Normal tasks
    COMPLEX = "complex"    # Architecture decisions, complex reasoning


@dataclass
class Message:
    """A message in a conversation."""
    
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ExecutionResult:
    """Result of an AI execution."""
    
    success: bool
    content: str
    provider: ModelProvider
    model: str
    tokens_used: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseExecutor(ABC):
    """Base class for AI executors."""
    
    @abstractmethod
    async def execute(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> ExecutionResult:
        """Execute a conversation with the AI."""
        pass
    
    @abstractmethod
    async def stream(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Stream a response from the AI."""
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the executor is healthy."""
        pass


class AnthropicExecutor(BaseExecutor):
    """Executor for Anthropic Claude API."""
    
    def __init__(self):
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.models = {
            ModelTier.SIMPLE: settings.simple_model,
            ModelTier.STANDARD: settings.primary_model,
            ModelTier.COMPLEX: settings.complex_model,
        }
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def execute(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        tier: ModelTier = ModelTier.STANDARD,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> ExecutionResult:
        """Execute a conversation with Claude."""
        start_time = datetime.utcnow()
        model = self.models[tier]
        
        try:
            # Convert messages to Anthropic format
            api_messages = [
                {"role": m.role, "content": m.content}
                for m in messages
                if m.role != "system"
            ]
            
            response = await self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt or "",
                messages=api_messages,
                **kwargs,
            )
            
            content = response.content[0].text if response.content else ""
            latency = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            # Calculate cost (approximate)
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            cost = self._calculate_cost(model, input_tokens, output_tokens)
            
            return ExecutionResult(
                success=True,
                content=content,
                provider=ModelProvider.ANTHROPIC,
                model=model,
                tokens_used=input_tokens + output_tokens,
                cost_usd=cost,
                latency_ms=latency,
                metadata={
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "stop_reason": response.stop_reason,
                },
            )
        
        except Exception as e:
            latency = (datetime.utcnow() - start_time).total_seconds() * 1000
            return ExecutionResult(
                success=False,
                content="",
                provider=ModelProvider.ANTHROPIC,
                model=model,
                latency_ms=latency,
                error=str(e),
            )
    
    async def stream(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        tier: ModelTier = ModelTier.STANDARD,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Stream a response from Claude."""
        model = self.models[tier]
        
        api_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role != "system"
        ]
        
        async with self.client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt or "",
            messages=api_messages,
            **kwargs,
        ) as stream:
            async for text in stream.text_stream:
                yield text
    
    async def health_check(self) -> bool:
        """Check if Anthropic API is accessible."""
        try:
            # Simple ping with minimal tokens
            response = await self.client.messages.create(
                model=settings.simple_model,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return bool(response.content)
        except Exception:
            return False
    
    def _calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Calculate cost in USD (approximate)."""
        # Pricing as of 2025 (per million tokens)
        pricing = {
            "claude-opus-4-5-20250514": {"input": 15.0, "output": 75.0},
            "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
            "claude-haiku-4-5-20250514": {"input": 0.25, "output": 1.25},
        }
        
        if model not in pricing:
            return 0.0
        
        rates = pricing[model]
        cost = (
            (input_tokens / 1_000_000) * rates["input"]
            + (output_tokens / 1_000_000) * rates["output"]
        )
        return round(cost, 6)


class OllamaExecutor(BaseExecutor):
    """Executor for local Ollama models (fallback)."""
    
    def __init__(self):
        # Use OpenAI-compatible API for Ollama
        self.client = AsyncOpenAI(
            base_url=f"{settings.ollama_base_url}/v1",
            api_key="ollama",  # Not used but required
        )
        self.model = settings.ollama_model
    
    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
    async def execute(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> ExecutionResult:
        """Execute a conversation with local Ollama model."""
        start_time = datetime.utcnow()
        
        try:
            # Convert messages to OpenAI format
            api_messages = []
            if system_prompt:
                api_messages.append({"role": "system", "content": system_prompt})
            
            api_messages.extend([
                {"role": m.role, "content": m.content}
                for m in messages
            ])
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=api_messages,
                max_tokens=max_tokens,
            )
            
            content = response.choices[0].message.content or ""
            latency = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            return ExecutionResult(
                success=True,
                content=content,
                provider=ModelProvider.OLLAMA,
                model=self.model,
                tokens_used=response.usage.total_tokens if response.usage else 0,
                cost_usd=0.0,  # Local is free
                latency_ms=latency,
            )
        
        except Exception as e:
            latency = (datetime.utcnow() - start_time).total_seconds() * 1000
            return ExecutionResult(
                success=False,
                content="",
                provider=ModelProvider.OLLAMA,
                model=self.model,
                latency_ms=latency,
                error=str(e),
            )
    
    async def stream(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Stream a response from Ollama."""
        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        
        api_messages.extend([
            {"role": m.role, "content": m.content}
            for m in messages
        ])
        
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=api_messages,
            max_tokens=max_tokens,
            stream=True,
        )
        
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    
    async def health_check(self) -> bool:
        """Check if Ollama is running and model is available."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{settings.ollama_base_url}/api/tags",
                    timeout=5.0,
                )
                if response.status_code == 200:
                    data = response.json()
                    models = [m["name"] for m in data.get("models", [])]
                    return self.model.split(":")[0] in [m.split(":")[0] for m in models]
            return False
        except Exception:
            return False


class ExecutionManager:
    """
    Manages AI execution with automatic fallback.
    
    Primary: Anthropic Claude (best quality)
    Fallback: Local Ollama (free, offline)
    """
    
    def __init__(self):
        self.anthropic: AnthropicExecutor | None = None
        self.ollama: OllamaExecutor | None = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize executors based on configuration."""
        if self._initialized:
            return
        
        # Initialize Anthropic if API key available
        if settings.anthropic_api_key:
            self.anthropic = AnthropicExecutor()
        
        # Initialize Ollama if enabled
        if settings.ollama_enabled:
            self.ollama = OllamaExecutor()
        
        self._initialized = True
    
    async def execute(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        tier: ModelTier = ModelTier.STANDARD,
        allow_fallback: bool = True,
        **kwargs: Any,
    ) -> ExecutionResult:
        """
        Execute with automatic fallback.
        
        Tries Anthropic first, falls back to Ollama if:
        - Anthropic fails
        - allow_fallback is True
        - Ollama is enabled
        """
        await self.initialize()
        
        # Try Anthropic first
        if self.anthropic:
            result = await self.anthropic.execute(
                messages=messages,
                system_prompt=system_prompt,
                tier=tier,
                **kwargs,
            )
            if result.success:
                return result
            
            # Log failure and try fallback
            if not allow_fallback:
                return result
        
        # Try Ollama fallback
        if self.ollama and allow_fallback:
            result = await self.ollama.execute(
                messages=messages,
                system_prompt=system_prompt,
                **kwargs,
            )
            return result
        
        # No executor available
        return ExecutionResult(
            success=False,
            content="",
            provider=ModelProvider.ANTHROPIC,
            model="none",
            error="No AI backend available. Configure ANTHROPIC_API_KEY or enable OLLAMA.",
        )
    
    async def stream(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
        tier: ModelTier = ModelTier.STANDARD,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Stream with automatic fallback."""
        await self.initialize()
        
        # Try Anthropic first
        if self.anthropic:
            try:
                async for chunk in self.anthropic.stream(
                    messages=messages,
                    system_prompt=system_prompt,
                    tier=tier,
                    **kwargs,
                ):
                    yield chunk
                return
            except Exception:
                pass  # Fall through to Ollama
        
        # Try Ollama fallback
        if self.ollama:
            async for chunk in self.ollama.stream(
                messages=messages,
                system_prompt=system_prompt,
                **kwargs,
            ):
                yield chunk
    
    async def health_check(self) -> dict[str, bool]:
        """Check health of all executors."""
        await self.initialize()
        
        results = {}
        
        if self.anthropic:
            results["anthropic"] = await self.anthropic.health_check()
        else:
            results["anthropic"] = False
        
        if self.ollama:
            results["ollama"] = await self.ollama.health_check()
        else:
            results["ollama"] = False
        
        return results
    
    def get_active_provider(self) -> ModelProvider:
        """Get the currently active provider."""
        if self.anthropic:
            return ModelProvider.ANTHROPIC
        if self.ollama:
            return ModelProvider.OLLAMA
        raise ValueError("No provider configured")


# Global instance
_manager: ExecutionManager | None = None


def get_execution_manager() -> ExecutionManager:
    """Get or create the global execution manager."""
    global _manager
    if _manager is None:
        _manager = ExecutionManager()
    return _manager
