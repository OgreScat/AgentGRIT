"""
AgentGRIT 5-Element Expert Persona Framework

Based on validated research showing 94%+ quality uplift vs generic "act as expert" prompts.
Personas are conditionally activated based on provider and task complexity.

Key principles:
1. Never use vague personas ("be helpful", "act as expert")
2. Always include: Role+Seniority, Domain, Narrow Focus, Methodologies, Constraints, Output Format
3. Activate full personas only for Claude (worth the tokens)
4. Use minimal personas for Perplexity/Grok (research/social focus)
5. Skip personas for Ollama (simple tasks, save context window)

Reference: https://reddit.com/r/PromptEngineering/comments/1oefkfe/
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
# PERSONA ACTIVATION BY PROVIDER
# ═══════════════════════════════════════════════════════════════════════════════

class PersonaMode(Enum):
    """How much persona context to inject."""
    FULL = "full"           # Complete 5-element persona (~150-200 tokens)
    MINIMAL = "minimal"     # Core focus only (~50 tokens)
    NONE = "none"           # Skip persona injection


PERSONA_ACTIVATION: dict[str, PersonaMode] = {
    "claude-opus": PersonaMode.FULL,      # Worth the tokens for complex reasoning
    "claude-sonnet": PersonaMode.FULL,    # Worth the tokens
    "claude-haiku": PersonaMode.MINIMAL,  # Lighter touch
    "perplexity": PersonaMode.MINIMAL,    # Research focus only
    "grok": PersonaMode.MINIMAL,          # Social context focus
    "ollama": PersonaMode.NONE,           # Simple tasks, save 8K context
}


# ═══════════════════════════════════════════════════════════════════════════════
# PERSONA DATA STRUCTURE
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Persona:
    """
    5-Element Expert Persona.

    All fields required for full persona; minimal mode uses only
    role_seniority + narrow_focus.
    """
    id: str
    role_seniority: str          # "Senior Data Engineer with 8 years experience"
    domain: str                   # "distributed ETL pipelines for analytics platforms"
    narrow_focus: str             # "schema drift detection in streaming data pipelines"
    methodologies: list[str]      # ["Apache Airflow", "dbt", "great_expectations"]
    constraints: str              # "$0 cloud budget, <150ms latency, single-node deploy"
    output_format: str            # "1. Prototype code\n2. Metrics\n3. Edge cases"
    triggers: list[str] = field(default_factory=list)  # Keywords that activate this persona

    def to_full_prompt(self) -> str:
        """Generate full 5-element persona prompt prefix."""
        methodologies_str = ", ".join(self.methodologies)
        return f"""You are a {self.role_seniority} in {self.domain}.

You specialize in {self.narrow_focus}.

Your core methodologies and frameworks: {methodologies_str}.

Your real-world constraints: {self.constraints}.

Output format you deliver: {self.output_format}.

---

"""

    def to_minimal_prompt(self) -> str:
        """Generate minimal persona prompt (role + focus only)."""
        return f"""You are a {self.role_seniority} specializing in {self.narrow_focus}.

---

"""


# ═══════════════════════════════════════════════════════════════════════════════
# PERSONA LIBRARY -- general-purpose starter personas
# ═══════════════════════════════════════════════════════════════════════════════

PERSONA_LIBRARY: dict[str, Persona] = {



    # AgentGRIT: Backend Architecture
    "backend_architect": Persona(
        id="backend_architect",
        role_seniority="Senior Backend Architect with 15 years at scale-up SaaS companies",
        domain="distributed systems and API design for AI/ML workloads",
        narrow_focus="multi-LLM orchestration, cost optimization, and self-governing agent systems",
        methodologies=[
            "Domain-driven design",
            "Event sourcing for audit trails",
            "Circuit breaker patterns for LLM APIs",
            "Capability-based routing",
        ],
        constraints="$100/month LLM budget across all providers, 4-week sprint cycles, team of 2 devs, prioritize reliability over feature velocity",
        output_format="1. Architecture diagram (described)\n2. Trade-offs table\n3. Implementation roadmap with effort estimates\n4. Risk mitigation",
        triggers=[
            "architecture", "distributed", "microservices", "scaling",
            "system design", "API design", "orchestration",
            "multi-LLM", "routing", "cost optimization",
        ],
    ),

    # AgentGRIT: DevOps / Infrastructure
    "devops_engineer": Persona(
        id="devops_engineer",
        role_seniority="Senior DevOps Engineer with 10 years in startup environments",
        domain="local-first development infrastructure and CI/CD",
        narrow_focus="Python packaging, Makefile automation, and Ollama/local LLM deployment",
        methodologies=[
            "12-factor app principles",
            "Makefile-driven workflows",
            "venv/pip for reproducible environments",
            "JSONL logging for observability",
        ],
        constraints="No cloud CI (GitHub Actions OK), local-first development on macOS, zero-cost infrastructure, must work offline",
        output_format="1. Shell commands to run\n2. File changes with diffs\n3. Verification steps\n4. Rollback procedure",
        triggers=[
            "Makefile", "CI/CD", "deployment", "Docker",
            "pip", "venv", "packaging", "pyproject.toml",
            "Ollama", "local LLM", "infrastructure",
        ],
    ),


    # General: Code Review
    "code_reviewer": Persona(
        id="code_reviewer",
        role_seniority="Principal Engineer with 18 years across multiple tech stacks",
        domain="code quality and security review",
        narrow_focus="Python/TypeScript security vulnerabilities, performance bottlenecks, and maintainability",
        methodologies=[
            "OWASP Top 10 security checklist",
            "Cognitive complexity analysis",
            "DRY/SOLID principles",
            "Performance profiling mindset",
        ],
        constraints="Review must be actionable within 1 hour of dev time, prioritize security over style, no bikeshedding",
        output_format="1. Critical issues (must fix)\n2. Important issues (should fix)\n3. Suggestions (nice to have)\n4. What's done well",
        triggers=[
            "code review", "review this", "security audit",
            "vulnerability", "refactor", "improve this code",
        ],
    ),

    # General: Technical Writer
    "technical_writer": Persona(
        id="technical_writer",
        role_seniority="Senior Technical Writer with 8 years in developer tools",
        domain="developer documentation and API references",
        narrow_focus="quickstart guides, README files, and inline code documentation",
        methodologies=[
            "Diátaxis documentation framework",
            "Show-don't-tell with runnable examples",
            "Progressive disclosure",
            "Copy-paste-ready code blocks",
        ],
        constraints="Docs must be scannable in <30 seconds, work for beginners and experts, no stale examples",
        output_format="1. Document structure\n2. Full content\n3. Code examples (tested)\n4. Cross-reference suggestions",
        triggers=[
            "documentation", "README", "quickstart", "guide",
            "API reference", "docstring", "comment",
        ],
    ),
}


# ═══════════════════════════════════════════════════════════════════════════════
# PERSONA SELECTION
# ═══════════════════════════════════════════════════════════════════════════════

def select_persona(
    task: str,
    category: Optional[str] = None,
) -> Optional[Persona]:
    """
    Auto-select the best persona for a task based on trigger keywords.

    Args:
        task: The task description
        category: Optional TaskCategory value for additional context

    Returns:
        Best matching Persona, or None if no good match
    """
    task_lower = task.lower()

    best_match: Optional[Persona] = None
    best_score = 0

    for persona in PERSONA_LIBRARY.values():
        score = 0
        for trigger in persona.triggers:
            if trigger.lower() in task_lower:
                # Longer triggers are more specific, worth more
                score += len(trigger)

        if score > best_score:
            best_score = score
            best_match = persona

    # Require minimum match quality (at least one trigger)
    if best_score < 5:
        return None

    return best_match


def get_persona_prompt(
    task: str,
    provider: str,
    category: Optional[str] = None,
) -> str:
    """
    Get the appropriate persona prompt prefix for a task.

    Args:
        task: The task description
        provider: LLM provider name (e.g., "claude-sonnet", "ollama")
        category: Optional TaskCategory value

    Returns:
        Persona prompt prefix (may be empty string if no persona applies)
    """
    # Check activation mode for this provider
    mode = PERSONA_ACTIVATION.get(provider, PersonaMode.NONE)

    if mode == PersonaMode.NONE:
        return ""

    # Select persona
    persona = select_persona(task, category)

    if persona is None:
        return ""

    # Generate appropriate prompt
    if mode == PersonaMode.FULL:
        return persona.to_full_prompt()
    elif mode == PersonaMode.MINIMAL:
        return persona.to_minimal_prompt()

    return ""


def get_persona_by_id(persona_id: str) -> Optional[Persona]:
    """Get a specific persona by ID."""
    return PERSONA_LIBRARY.get(persona_id)


def list_personas() -> list[str]:
    """List all available persona IDs."""
    return list(PERSONA_LIBRARY.keys())


# ═══════════════════════════════════════════════════════════════════════════════
# COMPLEXITY DETECTION (for PersonaBylaw)
# ═══════════════════════════════════════════════════════════════════════════════

COMPLEX_CATEGORIES = [
    "architecture",
    "refactor",
    "multi_file_refactor",
    "critical",
    "complex_architecture",
]


def is_complex_task(category: str) -> bool:
    """Check if a task category warrants persona enforcement."""
    return category.lower() in COMPLEX_CATEGORIES


# ═══════════════════════════════════════════════════════════════════════════════
# EXAMPLE USAGE
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Test persona selection
    test_tasks = [
        "Design the architecture for multi-LLM routing",
        "Fix the CI pipeline for Docker builds",
        "Review this code for SQL injection vulnerabilities",
        "Write a quickstart guide for the API",
        "Format this Python code nicely",  # Should return None (too simple)
    ]

    print("Persona Selection Test")
    print("=" * 60)

    for task in test_tasks:
        persona = select_persona(task)
        if persona:
            print(f"\nTask: {task[:50]}...")
            print(f"  → Persona: {persona.id}")
            print(f"  → Role: {persona.role_seniority[:50]}...")
        else:
            print(f"\nTask: {task[:50]}...")
            print(f"  → No persona (simple task)")

    print("\n" + "=" * 60)
    print("\nFull persona example (backend_architect for Claude):")
    print("-" * 60)
    prompt = get_persona_prompt(
        "Design the architecture for multi-LLM routing",
        "claude-sonnet"
    )
    print(prompt)
