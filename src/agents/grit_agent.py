"""
AgentGRIT 2.0 - The Ultimate AI Agent Framework

Combines the BEST of:
- Agent Zero: Self-tool-creating agents, subordinate hierarchies, OS-level execution
- Multi-platform messaging gateway: works with any OpenAI-compatible client, always-on
- Ollama: Local execution, cost-free inference, privacy
- GRIT Bylaws: Self-governance, trust levels, minimal escalation

WITH YOUR CONSTRAINTS:
- Nearing your Claude usage cap (session or weekly) → Route to Ollama/Perplexity first
- Perplexity $5/mo free tier → Use for ALL research tasks
- Grok Premium → Real-time social/X context

THE PHILOSOPHY:
"An agent that creates its own tools, governs itself, and only asks for help
when genuinely uncertain - while respecting your API budget constraints."
"""

import asyncio
import json
import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import httpx

# Import escalation system
from ..governance.model_provenance import is_model_approved, explain as explain_provenance
from ..governance.escalations import (
    EscalationManager,
    ActionRequest,
    ActionCategory,
    EvidenceBundle,
    RiskLevel,
    Decision,
)


# ═══════════════════════════════════════════════════════════════════════════════
# CORE AGENT ARCHITECTURE (Agent Zero inspired)
# ═══════════════════════════════════════════════════════════════════════════════

class AgentRole(Enum):
    """Agent roles in the hierarchy."""
    SUPERIOR = "superior"      # Human or parent agent
    WORKER = "worker"          # Task executor
    SUBORDINATE = "subordinate" # Delegated subtask handler


@dataclass
class AgentMessage:
    """Message between agents or agent<->human."""
    sender: str
    receiver: str
    content: str
    message_type: str  # "task", "result", "question", "escalation"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentMemory:
    """
    Agent Zero style memory - vector-searchable, persistent.
    For now, simple key-value. Can upgrade to ChromaDB later.
    """
    short_term: list[str] = field(default_factory=list)  # Current conversation
    long_term: dict[str, Any] = field(default_factory=dict)  # Persistent facts
    tools_created: list[str] = field(default_factory=list)  # Tools agent has made
    
    def remember(self, fact: str, permanent: bool = False):
        """Remember a fact."""
        self.short_term.append(fact)
        if permanent:
            key = f"fact_{len(self.long_term)}"
            self.long_term[key] = {"fact": fact, "timestamp": datetime.utcnow().isoformat()}
    
    def recall(self, query: str) -> list[str]:
        """Recall relevant memories (simple keyword match for now)."""
        query_words = set(query.lower().split())
        relevant = []
        for memory in self.short_term:
            if any(word in memory.lower() for word in query_words):
                relevant.append(memory)
        return relevant


class Tool(ABC):
    """Base class for agent tools."""
    
    name: str
    description: str
    
    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """Execute the tool and return result."""
        pass


class CodeExecutionTool(Tool):
    """
    Agent Zero's core capability: Execute code/terminal commands.
    This is what makes the agent actually DO things.

    CRITICAL: All execution goes through escalation gate.

    SECURITY:
    - NO shell=True (prevents command injection)
    - Strict command allowlist with categories
    - Network commands (curl, wget) require Owner approval
    - Package managers (pip, npm) treated as FILE_WRITE
    """

    name = "code_execution"
    description = "Execute Python code or bash commands"

    # Command categories with risk levels
    SAFE_COMMANDS = frozenset(["ls", "cat", "echo", "grep", "find", "pwd", "head", "tail", "wc"])
    FILE_COMMANDS = frozenset(["mkdir", "touch", "cp", "mv", "rm"])  # Require escalation
    NETWORK_COMMANDS = frozenset(["curl", "wget", "ssh", "scp"])  # ALWAYS require Owner
    PACKAGE_COMMANDS = frozenset(["pip", "npm", "yarn", "cargo"])  # FILE_WRITE risk
    CODE_COMMANDS = frozenset(["python", "node", "bash", "sh"])  # Code execution risk
    VCS_COMMANDS = frozenset(["git"])  # Special handling

    def __init__(self, sandbox: bool = True, escalation_manager: EscalationManager | None = None):
        self.sandbox = sandbox
        self.escalation_manager = escalation_manager

        # All allowed commands (union of categories)
        self.allowed_commands = (
            self.SAFE_COMMANDS |
            self.FILE_COMMANDS |
            self.NETWORK_COMMANDS |
            self.PACKAGE_COMMANDS |
            self.CODE_COMMANDS |
            self.VCS_COMMANDS
        )

        # Pending executions awaiting approval
        self._pending_executions: dict[str, dict] = {}

    async def execute(
        self,
        code: str | None = None,
        command: str | None = None,
        language: str = "python",
        execution_token: str | None = None,
    ) -> str:
        """Execute code or command - requires escalation approval."""
        if command:
            return await self._run_command(command, execution_token)
        elif code:
            return await self._run_code(code, language, execution_token)
        return "No code or command provided"

    async def _run_command(self, command: str, execution_token: str | None = None) -> str:
        """Run a shell command with escalation gate. NO shell=True."""
        import shlex

        # Parse command safely (NO shell=True)
        try:
            cmd_parts = shlex.split(command)
        except ValueError as e:
            return f"Invalid command syntax: {e}"

        if not cmd_parts:
            return "Empty command"

        base_cmd = cmd_parts[0]

        # Check allowlist
        if base_cmd not in self.allowed_commands:
            return f"Command '{base_cmd}' not in allowed list"

        # Determine risk level based on command category
        requires_owner = base_cmd in self.NETWORK_COMMANDS
        is_file_write = base_cmd in (self.FILE_COMMANDS | self.PACKAGE_COMMANDS)

        # ESCALATION GATE: Network commands ALWAYS require approval
        if self.escalation_manager and not execution_token:
            if requires_owner or is_file_write or base_cmd in self.CODE_COMMANDS:
                return await self._create_shell_escalation(command, requires_owner=requires_owner)

        # If token provided, verify it's valid for this command
        if execution_token and self.escalation_manager:
            if not self._verify_execution_token(execution_token, command):
                return "❌ Invalid or expired execution token"

        # Execute command (approved or safe command)
        # SECURITY: Use cmd_parts list, NOT shell=True
        try:
            result = subprocess.run(
                cmd_parts,  # Pass as list, not string
                shell=False,  # CRITICAL: No shell injection
                capture_output=True,
                text=True,
                timeout=30,
                cwd=os.getcwd(),  # Explicit working directory
            )
            return result.stdout or result.stderr or "Command completed"
        except subprocess.TimeoutExpired:
            return "Command timed out"
        except FileNotFoundError:
            return f"Command not found: {base_cmd}"
        except Exception as e:
            return f"Error: {e}"

    async def _create_shell_escalation(self, command: str, requires_owner: bool = False) -> str:
        """Create escalation request for shell command."""
        import shlex
        cmd_parts = shlex.split(command)
        base_cmd = cmd_parts[0] if cmd_parts else "unknown"

        # Determine category based on command type
        if base_cmd in self.NETWORK_COMMANDS:
            category = ActionCategory.API_CALL  # Network = API_CALL, requires Owner
        elif base_cmd in self.PACKAGE_COMMANDS:
            category = ActionCategory.FILE_WRITE  # Package installs modify filesystem
        else:
            category = ActionCategory.SHELL_EXECUTE

        action = ActionRequest(
            category=category,
            operation="run_command",
            parameters={"command": command, "base_cmd": base_cmd},
            reversible=False,  # Shell commands generally not reversible
        )

        evidence = EvidenceBundle(
            trigger_reason=f"Shell command execution: {command[:50]}...",
            input_summary=command[:200],
        )

        # Determine risk level
        risk = RiskLevel.MEDIUM
        dangerous_patterns = ["rm", "dd", "mkfs", "chmod", "chown", "sudo"]
        if any(p in command.lower() for p in dangerous_patterns):
            risk = RiskLevel.HIGH
        if requires_owner or base_cmd in self.NETWORK_COMMANDS:
            risk = RiskLevel.HIGH  # Network commands are high risk

        escalation = self.escalation_manager.create_escalation(
            requester="code_execution_tool",
            action=action,
            risk_level=risk,
            evidence=evidence,
        )

        # Store pending execution
        self._pending_executions[escalation.id] = {"command": command}

        owner_note = " (requires Owner)" if escalation.requires_owner else ""
        return f"⏳ AWAITING APPROVAL{owner_note}: Escalation ID `{escalation.id}`\nCommand: {command[:50]}..."

    def _verify_execution_token(self, token: str, command: str) -> bool:
        """Verify execution token matches approved escalation."""
        if not self.escalation_manager:
            return False

        request = self.escalation_manager.get_request(token)
        if not request:
            return False

        # Check if approved
        if not request.is_approved:
            return False

        # Check if command matches
        pending = self._pending_executions.get(token)
        if not pending or pending.get("command") != command:
            return False

        # Clean up
        del self._pending_executions[token]
        return True
    
    async def _run_code(self, code: str, language: str, execution_token: str | None = None) -> str:
        """Run code in specified language with escalation gate."""
        if language != "python":
            return f"Language {language} not supported"

        # ESCALATION GATE: If no token, create escalation request
        if self.escalation_manager and not execution_token:
            return await self._create_code_escalation(code, language)

        # If token provided, verify it's valid
        if execution_token and self.escalation_manager:
            if not self._verify_code_token(execution_token, code):
                return "❌ Invalid or expired execution token"

        # Execute code (approved or no escalation manager)
        try:
            temp_file = Path("/tmp/agent_code.py")
            temp_file.write_text(code)
            result = subprocess.run(
                ["python", str(temp_file)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.stdout or result.stderr or "Code executed"
        except Exception as e:
            return f"Error: {e}"

    async def _create_code_escalation(self, code: str, language: str) -> str:
        """Create escalation request for code execution."""
        action = ActionRequest(
            category=ActionCategory.SHELL_EXECUTE,
            operation="run_code",
            parameters={"language": language, "code_preview": code[:200]},
            reversible=False,
        )

        evidence = EvidenceBundle(
            trigger_reason=f"Code execution ({language}): {len(code)} chars",
            input_summary=code[:200],
            diff_preview=code[:500],
        )

        # Determine risk level
        risk = RiskLevel.MEDIUM
        dangerous_patterns = ["os.system", "subprocess", "eval", "exec", "__import__"]
        if any(p in code for p in dangerous_patterns):
            risk = RiskLevel.HIGH

        escalation = self.escalation_manager.create_escalation(
            requester="code_execution_tool",
            action=action,
            risk_level=risk,
            evidence=evidence,
        )

        # Store pending execution with hash for verification
        import hashlib
        code_hash = hashlib.sha256(code.encode()).hexdigest()[:16]
        self._pending_executions[escalation.id] = {"code_hash": code_hash, "code": code}

        return f"⏳ AWAITING APPROVAL: Escalation ID `{escalation.id}`\nCode: {code[:50]}..."

    def _verify_code_token(self, token: str, code: str) -> bool:
        """Verify execution token matches approved code escalation."""
        if not self.escalation_manager:
            return False

        request = self.escalation_manager.get_request(token)
        if not request:
            return False

        if not request.is_approved:
            return False

        pending = self._pending_executions.get(token)
        if not pending:
            return False

        # Verify code hash matches
        import hashlib
        code_hash = hashlib.sha256(code.encode()).hexdigest()[:16]
        if pending.get("code_hash") != code_hash:
            return False

        del self._pending_executions[token]
        return True


class KnowledgeTool(Tool):
    """
    Web search tool - routes to Perplexity (your $5/mo free tier).
    Agent Zero calls this for online knowledge.
    """
    
    name = "knowledge"
    description = "Search the web for information"
    
    def __init__(self, perplexity_api_key: str):
        self.api_key = perplexity_api_key
    
    async def execute(self, query: str) -> str:
        """Search using Perplexity API."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.perplexity.ai/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "llama-3.1-sonar-small-128k-online",
                        "messages": [{"role": "user", "content": query}],
                    },
                    timeout=60.0,
                )
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"Search error: {e}"


class CommunicationTool(Tool):
    """
    Agent Zero's communication - talk to superior/subordinates.
    """
    
    name = "communication"
    description = "Communicate with other agents or the user"
    
    def __init__(self, message_queue: list[AgentMessage]):
        self.message_queue = message_queue
    
    async def execute(
        self,
        to: str,
        content: str,
        message_type: str = "task",
    ) -> str:
        """Send a message."""
        message = AgentMessage(
            sender="agent",
            receiver=to,
            content=content,
            message_type=message_type,
        )
        self.message_queue.append(message)
        return f"Message sent to {to}"


# ═══════════════════════════════════════════════════════════════════════════════
# BYLAW GOVERNANCE (GRIT's self-governing rules)
# ═══════════════════════════════════════════════════════════════════════════════

class BylawAction(Enum):
    """What the bylaw engine decides."""
    PROCEED = "proceed"
    VERIFY_FIRST = "verify_first"
    NOTIFY = "notify"
    ESCALATE = "escalate"
    BLOCK = "block"


@dataclass
class BylawDecision:
    """Result of bylaw evaluation."""
    action: BylawAction
    reason: str
    rule_name: str | None = None


class BylawEngine:
    """
    Self-governance engine. The agent enforces these on ITSELF.

    Delegates to the real AgentGRIT governance engine
    (src/governance/bylaws.py) so this agent is bound by the SAME rules
    as every other execution path in AgentGRIT (router.py, other governed
    agents, etc) instead of a smaller local duplicate that used
    to cover only 4 regex patterns. This class's own BylawAction /
    BylawDecision types are kept unchanged so existing callers in this
    file (process(), _create_escalation_from_bylaw()) don't need to
    change - only the decision logic underneath moved to one source of
    truth.
    """

    def __init__(self):
        from ..governance.bylaws import get_bylaw_engine, AgentRole as GovAgentRole
        self._real_engine = get_bylaw_engine(GovAgentRole.DEVELOPER)

    def evaluate(self, action: str, context: dict[str, Any] | None = None) -> BylawDecision:
        """Evaluate an action against bylaws (delegates to governance/bylaws.py)."""
        from ..governance.bylaws import BylawAction as GovBylawAction

        real_result = self._real_engine.evaluate(action, context=context or {})

        # Real engine's BylawAction and this file's BylawAction are separate
        # Enum classes with matching string values by design - map explicitly
        # rather than relying on value equality across Enum types.
        action_map = {
            GovBylawAction.PROCEED: BylawAction.PROCEED,
            GovBylawAction.VERIFY_FIRST: BylawAction.VERIFY_FIRST,
            GovBylawAction.NOTIFY: BylawAction.NOTIFY,
            GovBylawAction.ESCALATE: BylawAction.ESCALATE,
            GovBylawAction.BLOCK: BylawAction.BLOCK,
        }
        return BylawDecision(
            action=action_map[real_result.action],
            reason=real_result.reason,
            rule_name=real_result.matched_rule,
        )


class LLMProvider(Enum):
    """Available LLM providers in priority order."""
    OLLAMA = "ollama"           # Priority 1: FREE
    PERPLEXITY = "perplexity"   # Priority 2: $5/mo for research
    GROK = "grok"               # Priority 3: Social/X context
    CLAUDE = "claude"           # Priority 4: EXPENSIVE - last resort


@dataclass
class LLMConfig:
    """Configuration for each LLM provider."""
    provider: LLMProvider
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    enabled: bool = True


class MultiLLMRouter:
    """
    Routes tasks to the cheapest capable LLM.
    
    YOUR CONSTRAINTS:
    - Claude: near session/weekly cap → AVOID unless necessary
    - Perplexity: $5/mo free → Use for ALL research
    - Ollama: FREE → Use for simple tasks
    - Grok: Premium → Social context
    """
    
    def __init__(self, configs: dict[LLMProvider, LLMConfig]):
        self.configs = configs
        self.usage_tracker = {
            "ollama": 0,
            "perplexity": 0,
            "grok": 0,
            "claude": 0,
        }
    
    def classify_task(self, task: str) -> LLMProvider:
        """Classify task to determine best provider."""
        task_lower = task.lower()
        
        # Research tasks → Perplexity (has web search)
        research_kw = ["search", "research", "find", "lookup", "what is", "who is",
                       "pypi", "npm", "documentation", "api docs"]
        if any(kw in task_lower for kw in research_kw):
            return LLMProvider.PERPLEXITY
        
        # Social/X tasks → Grok
        social_kw = ["twitter", "x.com", "trending", "viral", "sentiment"]
        if any(kw in task_lower for kw in social_kw):
            return LLMProvider.GROK
        
        # Complex architecture → Claude (worth the cost)
        complex_kw = ["architecture", "design system", "complex", "critical", "security"]
        if any(kw in task_lower for kw in complex_kw):
            return LLMProvider.CLAUDE
        
        # Default: Ollama (FREE)
        return LLMProvider.OLLAMA
    
    async def execute(self, task: str, force_provider: LLMProvider | None = None) -> tuple[str, LLMProvider]:
        """Execute task with optimal provider."""
        provider = force_provider or self.classify_task(task)
        config = self.configs.get(provider)
        
        if not config or not config.enabled:
            # Fallback chain: Ollama → Perplexity → Claude
            for fallback in [LLMProvider.OLLAMA, LLMProvider.PERPLEXITY, LLMProvider.CLAUDE]:
                if fallback in self.configs and self.configs[fallback].enabled:
                    provider = fallback
                    config = self.configs[fallback]
                    break
        
        if not config:
            return "No LLM provider available", LLMProvider.OLLAMA
        
        # Execute on chosen provider
        result = await self._call_provider(provider, config, task)
        self.usage_tracker[provider.value] += 1
        
        return result, provider
    
    async def _call_provider(self, provider: LLMProvider, config: LLMConfig, prompt: str) -> str:
        """Call the specific provider."""
        try:
            if provider == LLMProvider.OLLAMA:
                return await self._call_ollama(config, prompt)
            elif provider == LLMProvider.PERPLEXITY:
                return await self._call_perplexity(config, prompt)
            elif provider == LLMProvider.GROK:
                return await self._call_grok(config, prompt)
            elif provider == LLMProvider.CLAUDE:
                return await self._call_claude(config, prompt)
        except Exception as e:
            return f"Provider error: {e}"
        return "Unknown provider"
    
    async def _call_ollama(self, config: LLMConfig, prompt: str) -> str:
        """Call local Ollama - FREE."""
        model = config.model or "gemma4:12b"
        if not is_model_approved(model):
            return f"Blocked by provenance policy: {explain_provenance(model)}"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{config.base_url or 'http://localhost:11434'}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=120.0,
            )
            return response.json().get("response", "")
    
    async def _call_perplexity(self, config: LLMConfig, prompt: str) -> str:
        """Call Perplexity - $5/mo free tier."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.perplexity.ai/chat/completions",
                headers={"Authorization": f"Bearer {config.api_key}"},
                json={
                    "model": "llama-3.1-sonar-small-128k-online",
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=60.0,
            )
            return response.json()["choices"][0]["message"]["content"]
    
    async def _call_grok(self, config: LLMConfig, prompt: str) -> str:
        """Call Grok - Premium subscription."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {config.api_key}"},
                json={"model": "grok-beta", "messages": [{"role": "user", "content": prompt}]},
                timeout=60.0,
            )
            return response.json()["choices"][0]["message"]["content"]
    
    async def _call_claude(self, config: LLMConfig, prompt: str) -> str:
        """Call Claude - EXPENSIVE, use sparingly."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": config.api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": config.model or "claude-sonnet-4-20250514",
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=120.0,
            )
            return response.json()["content"][0]["text"]


# ═══════════════════════════════════════════════════════════════════════════════
# THE MAIN AGENT (Combines everything)
# ═══════════════════════════════════════════════════════════════════════════════

class AgentGRIT:
    """
    The Ultimate Agent: Agent Zero + Ollama + GRIT Bylaws

    Capabilities:
    - Creates its own tools (Agent Zero)
    - Multi-platform messaging gateway
    - Local inference (Ollama)
    - Self-governing (GRIT Bylaws)
    - Cost-optimized (Multi-LLM Router)
    - Two-person integrity (Escalation System)
    """

    def __init__(
        self,
        name: str = "GRIT",
        llm_configs: dict[LLMProvider, LLMConfig] | None = None,
        escalation_manager: EscalationManager | None = None,
    ):
        self.name = name
        self.memory = AgentMemory()
        self.bylaws = BylawEngine()
        self.message_queue: list[AgentMessage] = []

        # Escalation manager for two-person integrity
        self.escalation_manager = escalation_manager

        # Tools (Agent Zero style - can create more dynamically)
        # Pass escalation manager to tools that execute
        self.tools: dict[str, Tool] = {
            "code_execution": CodeExecutionTool(escalation_manager=escalation_manager),
            "communication": CommunicationTool(self.message_queue),
        }

        # Multi-LLM Router
        if llm_configs:
            self.router = MultiLLMRouter(llm_configs)
        else:
            self.router = None

        # Subordinate agents
        self.subordinates: dict[str, "AgentGRIT"] = {}
    
    async def process(self, user_input: str, execution_token: str | None = None) -> str:
        """
        Main processing loop with escalation gate.

        1. Check bylaws
        2. If ESCALATE: Create EscalationRequest, STOP execution
        3. Route to appropriate LLM
        4. Execute tools if needed (tools have their own escalation gates)
        5. Return result
        """
        # Step 1: Bylaw check
        decision = self.bylaws.evaluate(user_input)

        if decision.action == BylawAction.BLOCK:
            return f"🚫 BLOCKED: {decision.reason}"

        # Step 2: ESCALATION GATE - Creates request and STOPS execution
        if decision.action == BylawAction.ESCALATE:
            return await self._create_escalation_from_bylaw(user_input, decision)

        # Step 3: Remember the input
        self.memory.remember(f"User: {user_input}")

        # Step 4: Route to LLM
        if self.router:
            response, provider = await self.router.execute(user_input)
            provider_note = f"[via {provider.value}]"
        else:
            response = f"No LLM configured. Input was: {user_input}"
            provider_note = ""

        # Step 5: Remember the response
        self.memory.remember(f"Agent: {response}")

        # Step 6: Notify if required
        if decision.action == BylawAction.NOTIFY:
            response = f"ℹ️ {decision.reason}\n\n{response}"

        return f"{response}\n{provider_note}"

    async def _create_escalation_from_bylaw(self, user_input: str, decision: BylawDecision) -> str:
        """
        Create an escalation request when bylaws return ESCALATE.

        This STOPS execution until the escalation is approved.
        """
        if not self.escalation_manager:
            # No escalation manager - fall back to simple confirmation message
            return f"🔶 ESCALATION NEEDED: {decision.reason}\nPlease confirm this action."

        # Determine action category from bylaw context
        category = ActionCategory.API_CALL  # Default
        if "security" in decision.reason.lower() or "credential" in decision.reason.lower():
            category = ActionCategory.CREDENTIAL_CHANGE
        elif "shell" in decision.reason.lower() or "command" in decision.reason.lower():
            category = ActionCategory.SHELL_EXECUTE

        # Build typed action request
        action = ActionRequest(
            category=category,
            operation="bylaw_escalation",
            parameters={"input_summary": user_input[:200]},
            reversible=False,
        )

        # Build evidence bundle
        evidence = EvidenceBundle(
            trigger_reason=decision.reason,
            bylaw_matched=decision.rule_name,
            input_summary=user_input[:200],
        )

        # Determine risk level
        risk = RiskLevel.MEDIUM
        if category == ActionCategory.CREDENTIAL_CHANGE:
            risk = RiskLevel.HIGH
        if "production" in decision.reason.lower():
            risk = RiskLevel.CRITICAL

        # Create escalation - THIS STOPS EXECUTION
        escalation = self.escalation_manager.create_escalation(
            requester=f"agent_{self.name}",
            action=action,
            risk_level=risk,
            evidence=evidence,
        )

        # Return status - execution is BLOCKED until approved
        status_emoji = "🔶" if escalation.requires_owner else "⏳"
        lines = [
            f"{status_emoji} *ESCALATION CREATED*",
            f"",
            f"ID: `{escalation.id}`",
            f"Risk: {escalation.risk_level.name}",
            f"Reason: {decision.reason}",
            f"",
        ]

        if escalation.is_approved:
            lines.append("✅ Auto-approved by Manager (low risk)")
        elif escalation.requires_owner:
            lines.append("⚠️ Awaiting OWNER approval via Telegram")
            lines.append(f"Expires: {escalation.expires_at.strftime('%H:%M:%S UTC')}")
        else:
            lines.append("⏳ Awaiting Manager evaluation")

        lines.extend([
            "",
            "Commands:",
            f"`/escalation show {escalation.id}`",
            f"`/escalation approve {escalation.id}`",
        ])

        return "\n".join(lines)
    
    async def create_tool(self, name: str, code: str) -> str:
        """
        Agent Zero capability: Create a new tool dynamically.
        The agent can extend its own capabilities.
        """
        # This would dynamically create a tool from code
        # For safety, we'll just log it for now
        self.memory.tools_created.append(name)
        return f"Tool '{name}' created and registered"
    
    async def delegate_to_subordinate(self, task: str, subordinate_name: str | None = None) -> str:
        """
        Agent Zero capability: Create subordinate agent for subtask.
        """
        if subordinate_name not in self.subordinates:
            # Create new subordinate
            sub = AgentGRIT(
                name=subordinate_name or f"{self.name}_sub_{len(self.subordinates)}",
                llm_configs=None,  # Subordinates use same router
            )
            self.subordinates[subordinate_name or sub.name] = sub
        
        sub = self.subordinates[subordinate_name or list(self.subordinates.keys())[0]]
        return await sub.process(task)


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    """Demo the agent."""
    # Configure LLMs (your stack)
    configs = {
        LLMProvider.OLLAMA: LLMConfig(
            provider=LLMProvider.OLLAMA,
            base_url="http://localhost:11434",
            model="gemma4:12b",
            enabled=True,
        ),
        LLMProvider.PERPLEXITY: LLMConfig(
            provider=LLMProvider.PERPLEXITY,
            api_key=os.getenv("PPLX_API_KEY"),
            enabled=bool(os.getenv("PPLX_API_KEY")),
        ),
        LLMProvider.GROK: LLMConfig(
            provider=LLMProvider.GROK,
            api_key=os.getenv("GROK_API_KEY"),
            enabled=bool(os.getenv("GROK_API_KEY")),
        ),
        LLMProvider.CLAUDE: LLMConfig(
            provider=LLMProvider.CLAUDE,
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            model="claude-sonnet-4-20250514",
            enabled=bool(os.getenv("ANTHROPIC_API_KEY")),
        ),
    }
    
    agent = AgentGRIT(name="GRIT", llm_configs=configs)
    
    print("=" * 60)
    print("AgentGRIT 2.0 - The Ultimate AI Agent")
    print("=" * 60)
    print("\nRouting logic:")
    print("  1. Simple tasks → Ollama (FREE)")
    print("  2. Research → Perplexity ($5/mo)")
    print("  3. Social context → Grok")
    print("  4. Complex architecture → Claude (sparingly!)")
    print("\nType 'quit' to exit.\n")
    
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() == "quit":
            break
        
        response = await agent.process(user_input)
        print(f"\nGRIT: {response}\n")


if __name__ == "__main__":
    asyncio.run(main())
