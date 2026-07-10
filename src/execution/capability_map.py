"""
AgentGRIT 2.0 - LLM Capability Map

CRITICAL FIX: Prevents asking models to do things they can't reliably do.

The Problem (from earlier session):
- GLM-4.7-flash was asked to do multi-step agentic tool orchestration
- It ran for 30+ minutes, printed "PERFECT! FILE CREATED!"
- Zero files actually created - model was hallucinating tool use

Solution: Explicit capability mapping
- Each model has documented capabilities and limitations
- Router checks capability BEFORE routing
- Never ask Ollama to do complex tool orchestration
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Capability(Enum):
    """Capabilities that models may or may not have."""
    
    # Text generation
    TEXT_GENERATION = "text_generation"
    CODE_GENERATION = "code_generation"
    CODE_EXPLANATION = "code_explanation"
    
    # Reasoning
    SIMPLE_REASONING = "simple_reasoning"
    COMPLEX_REASONING = "complex_reasoning"
    MATHEMATICAL = "mathematical"
    
    # Tool use
    SINGLE_TOOL_CALL = "single_tool_call"
    MULTI_TOOL_ORCHESTRATION = "multi_tool"
    FILE_OPERATIONS = "file_operations"
    
    # Context
    SHORT_CONTEXT = "short_context"
    MEDIUM_CONTEXT = "medium_context"
    LONG_CONTEXT = "long_context"
    
    # Specialized
    WEB_SEARCH = "web_search"
    REALTIME_DATA = "realtime_data"
    IMAGE_UNDERSTANDING = "image_understanding"
    
    # Quality
    HIGH_ACCURACY = "high_accuracy"
    CREATIVE_WRITING = "creative_writing"
    TECHNICAL_WRITING = "technical_writing"


@dataclass
class ModelCapabilities:
    """Capability profile for a specific model."""
    model_id: str
    provider: str
    capabilities: dict[Capability, float] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    best_for: list[str] = field(default_factory=list)
    avoid_for: list[str] = field(default_factory=list)
    cost_tier: str = "free"
    
    def can_do(self, capability: Capability, min_reliability: float = 0.7) -> bool:
        return self.capabilities.get(capability, 0.0) >= min_reliability
    
    def reliability_for(self, capability: Capability) -> float:
        return self.capabilities.get(capability, 0.0)


# Model profiles
OLLAMA_QWEN3_CODER_30B = ModelCapabilities(
    model_id="qwen3-coder:30b",
    provider="ollama",
    capabilities={
        Capability.TEXT_GENERATION: 0.9,
        Capability.CODE_GENERATION: 0.85,
        Capability.CODE_EXPLANATION: 0.9,
        Capability.SIMPLE_REASONING: 0.8,
        Capability.COMPLEX_REASONING: 0.5,
        Capability.SINGLE_TOOL_CALL: 0.6,
        Capability.MULTI_TOOL_ORCHESTRATION: 0.2,  # UNRELIABLE!
        Capability.FILE_OPERATIONS: 0.3,  # Often hallucinates
        Capability.MEDIUM_CONTEXT: 0.8,
        Capability.TECHNICAL_WRITING: 0.8,
    },
    limitations=[
        "CANNOT reliably orchestrate multiple tool calls",
        "CANNOT reliably verify its own file operations",
        "Often claims success without actual execution",
    ],
    best_for=["Code formatting", "Code explanation", "Simple generation"],
    avoid_for=["Multi-file refactoring", "Autonomous tool use", "Complex reasoning"],
    cost_tier="free",
)

OLLAMA_GEMMA4_12B = ModelCapabilities(
    model_id="gemma4:12b",
    provider="ollama",
    capabilities={
        # Provisional estimates pending real eval data from this project's
        # own suite (src/evals/) — treat as unproven until evals confirm.
        # Do not cite these as benchmarked numbers.
        Capability.TEXT_GENERATION: 0.85,
        Capability.CODE_GENERATION: 0.8,
        Capability.CODE_EXPLANATION: 0.85,
        Capability.SIMPLE_REASONING: 0.75,
        Capability.COMPLEX_REASONING: 0.5,
        Capability.SINGLE_TOOL_CALL: 0.6,
        Capability.MULTI_TOOL_ORCHESTRATION: 0.3,  # unproven — verify before trusting
        Capability.FILE_OPERATIONS: 0.4,  # unproven — verify before trusting
        Capability.MEDIUM_CONTEXT: 0.8,
        Capability.TECHNICAL_WRITING: 0.75,
        Capability.IMAGE_UNDERSTANDING: 0.6,  # gemma4 is multimodal; unbenchmarked here
    },
    limitations=[
        "Capability numbers above are provisional, not eval-verified",
        "Multi-tool orchestration and file operations not yet trust-tested",
    ],
    best_for=["Code formatting", "Code explanation", "Simple generation", "Low-risk local work"],
    avoid_for=["Multi-file refactoring", "Autonomous tool use until evals pass", "Complex reasoning"],
    cost_tier="free",
)

PERPLEXITY_SONAR = ModelCapabilities(
    model_id="llama-3.1-sonar-small-128k-online",
    provider="perplexity",
    capabilities={
        Capability.TEXT_GENERATION: 0.85,
        Capability.WEB_SEARCH: 1.0,
        Capability.REALTIME_DATA: 0.9,
        Capability.LONG_CONTEXT: 0.9,
    },
    limitations=["No tool calling", "Cannot execute code"],
    best_for=["Web research", "Documentation lookup", "Current events"],
    avoid_for=["Code execution", "File operations"],
    cost_tier="cheap",
)

CLAUDE_SONNET = ModelCapabilities(
    model_id="claude-sonnet-4-20250514",
    provider="anthropic",
    capabilities={
        Capability.TEXT_GENERATION: 0.95,
        Capability.CODE_GENERATION: 0.95,
        Capability.COMPLEX_REASONING: 0.9,
        Capability.MULTI_TOOL_ORCHESTRATION: 0.85,
        Capability.FILE_OPERATIONS: 0.85,
        Capability.HIGH_ACCURACY: 0.9,
    },
    limitations=["Expensive - use sparingly"],
    best_for=["Complex code", "Tool orchestration", "Architecture"],
    avoid_for=["Simple tasks (use Ollama)", "Web research (use Perplexity)"],
    cost_tier="medium",
)


class CapabilityRegistry:
    """Registry of model capabilities."""
    
    def __init__(self):
        self.models = {
            "qwen3-coder:30b": OLLAMA_QWEN3_CODER_30B,  # forbidden by provenance policy — kept as reference only
            "gemma4:12b": OLLAMA_GEMMA4_12B,
            "llama-3.1-sonar-small-128k-online": PERPLEXITY_SONAR,
            "claude-sonnet-4-20250514": CLAUDE_SONNET,
        }
    
    def can_do(self, model_id: str, capability: Capability, min_reliability: float = 0.7) -> bool:
        model = self.models.get(model_id)
        return model.can_do(capability, min_reliability) if model else False
    
    def validate_task(self, model_id: str, required: list[Capability]) -> tuple[bool, list[str]]:
        model = self.models.get(model_id)
        if not model:
            return False, [f"Unknown model: {model_id}"]
        
        problems = []
        for cap in required:
            rel = model.reliability_for(cap)
            if rel < 0.5:
                problems.append(f"{model_id} cannot do {cap.value} (reliability: {rel:.0%})")
        
        return len(problems) == 0, problems


# Task requirements
TASK_REQUIREMENTS = {
    "format_code": [Capability.CODE_GENERATION],
    "explain_code": [Capability.CODE_EXPLANATION],
    "web_research": [Capability.WEB_SEARCH],
    "architecture_design": [Capability.COMPLEX_REASONING],
    "autonomous_coding": [Capability.MULTI_TOOL_ORCHESTRATION, Capability.FILE_OPERATIONS],
}
