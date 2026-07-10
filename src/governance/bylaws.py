"""
AgentGRIT Universal Bylaws v2

The self-governance rules that agents enforce on themselves.
These are NOT approval gates - they are autonomous behavior constraints.

v2 Changes (from Part 2 conversation):
- Role separation: Observer, Executor, etc. have different capabilities
- Config-enforced gates: deny bash/exec at config level
- PRs/approvals only: changes land via PRs, not direct writes
- Evidence bundles: Every decision logged with reasoning

Inspired by Asimov's Laws of Robotics, adapted for AI coding agents.

Zeroth Law: an agent must not, through silence or inaction, allow a
foreseeable harm to the human's interests, the project's integrity, or
anyone's safety to go unreported. Finding a real risk and not mentioning
it is its own failure mode -- see the repo_publish EscalationTrigger
below, added specifically because an earlier self-grade found that
publishing a repository publicly triggered zero escalation under the
rules as originally written. Surfacing a real risk is never optional,
even when nobody asked.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable


# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

from src.utils.logging import log_bylaw_decision as _log_bylaw_decision


# ═══════════════════════════════════════════════════════════════════════════════
# ROLE SYSTEM (v2)
# Different roles have different capabilities
# ═══════════════════════════════════════════════════════════════════════════════

class AgentRole(Enum):
    """Roles determine what actions an agent can take."""

    OBSERVER = "observer"      # 24/7 read-only (e.g. websocket/API polling)
    ANALYST = "analyst"        # Can analyze, cannot execute
    DEVELOPER = "developer"    # Can write code, PRs only
    EXECUTOR = "executor"      # Gated external actions; dry-run first
    ADMIN = "admin"            # Full capabilities


@dataclass
class RoleCapabilities:
    """What a role is allowed to do."""

    can_read_files: bool = True
    can_write_files: bool = False
    can_execute_bash: bool = False
    can_execute_python: bool = False
    can_make_api_calls: bool = False
    can_modify_database: bool = False
    can_create_pr: bool = False
    can_push_direct: bool = False  # Even admins should prefer PRs
    can_transact: bool = False
    max_cost_usd: float = 0.0
    allowed_paths: list[str] = field(default_factory=list)
    denied_paths: list[str] = field(default_factory=list)


ROLE_CAPABILITIES: dict[AgentRole, RoleCapabilities] = {
    AgentRole.OBSERVER: RoleCapabilities(
        can_read_files=True,
        can_write_files=False,
        can_execute_bash=False,
        can_execute_python=False,
        can_make_api_calls=True,  # Read-only APIs
        can_modify_database=False,
        max_cost_usd=0.01,
    ),
    AgentRole.ANALYST: RoleCapabilities(
        can_read_files=True,
        can_write_files=False,
        can_execute_bash=False,
        can_execute_python=True,  # Analysis scripts only
        can_make_api_calls=True,
        can_modify_database=False,
        max_cost_usd=0.10,
    ),
    AgentRole.DEVELOPER: RoleCapabilities(
        can_read_files=True,
        can_write_files=True,
        can_execute_bash=True,  # For git, npm, etc.
        can_execute_python=True,
        can_make_api_calls=True,
        can_modify_database=False,
        can_create_pr=True,  # Changes via PRs only
        can_push_direct=False,
        max_cost_usd=1.00,
    ),
    AgentRole.EXECUTOR: RoleCapabilities(
        can_read_files=True,
        can_write_files=False,
        can_execute_bash=False,
        can_execute_python=True,
        can_make_api_calls=True,
        can_modify_database=True,  # Transaction logging
        can_transact=True,
        max_cost_usd=10.00,  # Per transaction
    ),
    AgentRole.ADMIN: RoleCapabilities(
        can_read_files=True,
        can_write_files=True,
        can_execute_bash=True,
        can_execute_python=True,
        can_make_api_calls=True,
        can_modify_database=True,
        can_create_pr=True,
        can_push_direct=True,  # Only for emergencies
        can_transact=True,
        max_cost_usd=100.00,
    ),
}


class BylawAction(Enum):
    """Actions the bylaw engine can take."""
    
    PROCEED = "proceed"           # Action is safe, continue
    VERIFY_FIRST = "verify_first" # Run verification before proceeding
    NOTIFY = "notify"             # Inform human but proceed
    ESCALATE = "escalate"         # Ask human for decision (rare)
    BLOCK = "block"               # Never execute, no exceptions


@dataclass
class BylawResult:
    """Result of bylaw evaluation."""
    
    action: BylawAction
    reason: str
    matched_rule: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    
    @property
    def should_proceed(self) -> bool:
        """Check if action should proceed (possibly after verification)."""
        return self.action in (BylawAction.PROCEED, BylawAction.VERIFY_FIRST, BylawAction.NOTIFY)
    
    @property
    def needs_verification(self) -> bool:
        """Check if verification is required before proceeding."""
        return self.action == BylawAction.VERIFY_FIRST
    
    @property
    def needs_human(self) -> bool:
        """Check if human intervention is required."""
        return self.action == BylawAction.ESCALATE


# ═══════════════════════════════════════════════════════════════════════════════
# LAW 0: ABSOLUTE BLOCKS
# Never execute. No exceptions. No overrides. Ever.
# ═══════════════════════════════════════════════════════════════════════════════

BLOCKED_PATTERNS: list[tuple[str, str]] = [
    # Destructive file operations
    (r"rm\s+-rf\s+[/~]", "Recursive delete from root or home"),
    (r"rm\s+-rf\s+\*", "Recursive delete with wildcard"),
    (r"rm\s+-rf\s+\.\.", "Recursive delete parent directory"),
    (r"rm\s+-rf\s+/(?!tmp|var/tmp)", "Recursive delete system directory"),
    
    # Database destruction
    (r"DROP\s+(TABLE|DATABASE|SCHEMA)", "Database object destruction"),
    (r"TRUNCATE\s+TABLE", "Table truncation"),
    (r"DELETE\s+FROM\s+\w+\s*;?\s*$", "Delete all rows (no WHERE clause)"),
    
    # Git disasters
    (r"git\s+push.*--force.*main", "Force push to main branch"),
    (r"git\s+push.*--force.*master", "Force push to master branch"),
    (r"git\s+push.*-f.*main", "Force push to main branch"),
    (r"git\s+push.*-f.*master", "Force push to master branch"),
    (r"git\s+reset\s+--hard.*HEAD~", "Hard reset commits"),
    
    # Remote code execution
    (r"curl.*\|\s*(ba)?sh", "Pipe remote content to shell"),
    (r"wget.*\|\s*(ba)?sh", "Pipe remote content to shell"),
    (r"curl.*\|\s*python", "Pipe remote content to Python"),
    
    # System destruction
    (r"chmod\s+777", "World-writable permissions"),
    (r"chmod\s+-R\s+777", "Recursive world-writable permissions"),
    (r">(>)?\s*/etc/", "Write to /etc"),
    (r"mkfs\.", "Format filesystem"),
    (r"dd\s+if=.*/dev/", "Raw disk write"),
    (r":(){ :\|:& };:", "Fork bomb"),
    
    # Credential exposure
    (r"echo.*\$.*API.*KEY.*>", "Echo API key to file"),
    (r"cat.*\.env.*\|", "Pipe .env to another command"),
    (r"printenv.*KEY", "Print environment key to stdout"),
    (r"env\s*\|.*grep.*KEY", "Grep environment for keys"),

    # Container escape / privilege escalation
    (r"docker\s+run.*--privileged", "Privileged container execution"),
    (r"nsenter\s+", "Namespace enter (container escape)"),

    # Network exfiltration of secrets
    (r"curl.*-d.*\$.*KEY", "POST API key via curl"),
    (r"wget.*--post-data.*\$.*KEY", "POST API key via wget"),
]


# ═══════════════════════════════════════════════════════════════════════════════
# LAW 1: VERIFICATION REQUIREMENTS
# What must pass before committing changes.
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class VerificationConfig:
    """Configuration for self-verification checks."""
    
    # Required checks (must pass)
    required: list[str] = field(default_factory=lambda: [
        "syntax_valid",
        "tests_pass",
    ])
    
    # Recommended checks (should pass, but can proceed if not)
    recommended: list[str] = field(default_factory=lambda: [
        "lint_clean",
        "type_check",
        "builds",
    ])
    
    # Retry configuration
    max_retries: int = 3
    escalate_after_retries: bool = True
    
    # Files to skip verification for
    skip_patterns: list[str] = field(default_factory=lambda: [
        "*.md",
        "*.txt",
        "*.json",
        ".gitignore",
        "LICENSE",
        "README*",
    ])
    
    def should_skip(self, filepath: str) -> bool:
        """Check if file should skip verification."""
        path = Path(filepath)
        for pattern in self.skip_patterns:
            if path.match(pattern):
                return True
        return False


VERIFICATION = VerificationConfig()


# ═══════════════════════════════════════════════════════════════════════════════
# LAW 2: ESCALATION TRIGGERS
# When to ask a human (should be rare).
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class EscalationTrigger:
    """Definition of when to escalate to human."""
    
    name: str
    description: str
    patterns: list[str] = field(default_factory=list)
    condition: str | None = None
    threshold: float | None = None
    action: BylawAction = BylawAction.ESCALATE


ESCALATION_TRIGGERS: list[EscalationTrigger] = [
    EscalationTrigger(
        name="multiple_valid_architectures",
        description="Two or more valid approaches with materially different tradeoffs",
        action=BylawAction.ESCALATE,
    ),
    EscalationTrigger(
        name="cost_implication",
        description="Action would incur monetary cost above threshold",
        threshold=1.00,  # USD
        action=BylawAction.ESCALATE,
    ),
    EscalationTrigger(
        name="security_sensitive",
        description="Credentials, auth, permissions, secrets",
        patterns=[
            r"(api[_-]?key|password|secret|token)\s*[:=]",
            r"\.env\b",
            r"credentials",
            r"chmod\s+[0-7]{3}",
            r"ssh[_-]?key",
            r"private[_-]?key",
        ],
        action=BylawAction.ESCALATE,
    ),
    EscalationTrigger(
        name="repo_publish",
        description="Publishing a repo or changing repo visibility to public",
        patterns=[
            r"gh\s+repo\s+create\b.*--public",
            r"gh\s+repo\s+create\b.*--source",
            r"gh\s+repo\s+edit\b.*--visibility[\s=]+public",
            r"git\s+remote\s+add\b",
        ],
        action=BylawAction.ESCALATE,
    ),
    EscalationTrigger(
        name="scope_expansion",
        description="Task requires files outside defined project boundary",
        action=BylawAction.NOTIFY,  # Inform but don't block
    ),
    EscalationTrigger(
        name="persistent_failure",
        description="Cannot resolve after max_retries",
        action=BylawAction.ESCALATE,
    ),
    EscalationTrigger(
        name="breaking_change",
        description="Changes that would break existing functionality",
        patterns=[
            r"BREAKING\s*CHANGE",
            r"@deprecated",
            r"remove.*backward.*compat",
        ],
        action=BylawAction.NOTIFY,
    ),
]


# ═══════════════════════════════════════════════════════════════════════════════
# LAW 3: REPORTING REQUIREMENTS
# What to tell the human (inform, don't ask).
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ReportingConfig:
    """Configuration for what to report to human."""
    
    # Always notify about these events
    always_notify: list[str] = field(default_factory=lambda: [
        "task_complete",
        "task_failed",
        "escalation_triggered",
        "blocked_action_attempted",
        "trust_level_changed",
    ])
    
    # Batch into digest notifications
    batch_for_digest: list[str] = field(default_factory=lambda: [
        "file_created",
        "file_modified",
        "test_passed",
        "lint_fixed",
    ])
    
    # Never hide these
    never_hide: list[str] = field(default_factory=lambda: [
        "errors",
        "assumptions_made",
        "scope_changes",
        "security_relevant_actions",
    ])
    
    # Suppress these (too noisy)
    suppress: list[str] = field(default_factory=lambda: [
        "routine_file_reads",
        "intermediate_steps",
        "retry_attempts",
    ])
    
    # Digest interval
    digest_interval_hours: int = 4


REPORTING = ReportingConfig()


# ═══════════════════════════════════════════════════════════════════════════════
# LAW 4: TRACKING REQUIREMENTS
# Marge-style audit trail.
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TrackingConfig:
    """Configuration for audit trail tracking."""
    
    issue_prefix: str = "GRIT"
    
    # Documentation files to maintain
    docs: dict[str, str] = field(default_factory=lambda: {
        "tasklist": ".grit/tasklist.md",
        "assessment": ".grit/assessment.md",
        "decisions": ".grit/decisions.md",
        "instructions": ".grit/instructions.md",
    })
    
    retention_days: int = 90


TRACKING = TrackingConfig()


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG-ENFORCED GATES (v2)
# These are hard limits that cannot be overridden at runtime
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class GateConfig:
    """
    Config-enforced gates.

    These are set at startup and CANNOT be changed at runtime.
    Even if a user asks to override, the gate refuses.
    """

    # Hard denials - these commands are NEVER allowed
    deny_bash_patterns: list[str] = field(default_factory=lambda: [
        r"curl.*\|",  # Piped curl
        r"wget.*\|",  # Piped wget
        r"rm\s+-rf",  # Recursive delete
        r">\s*/dev/",  # Write to device
        r"eval\s*\(",  # Dynamic eval
        r"exec\s*\(",  # Dynamic exec
    ])

    # Hard denials - these paths are NEVER writable
    deny_paths: list[str] = field(default_factory=lambda: [
        "/etc/",
        "/usr/",
        "/bin/",
        "/sbin/",
        "~/.ssh/",
        "~/.gnupg/",
        "~/.aws/",
        ".env",  # Secrets file
    ])

    # Require PRs for these paths (no direct writes)
    require_pr_paths: list[str] = field(default_factory=lambda: [
        "src/",
        "lib/",
        "app/",
        "*.py",
        "*.ts",
        "*.js",
    ])

    # Maximum cost per action (USD)
    max_cost_per_action: float = 1.00

    # Maximum total cost per session (USD)
    max_cost_per_session: float = 10.00

    def is_bash_denied(self, command: str) -> tuple[bool, str]:
        """Check if bash command is denied by config."""
        for pattern in self.deny_bash_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return True, f"Bash pattern denied: {pattern}"
        return False, ""

    def is_path_denied(self, path: str) -> tuple[bool, str]:
        """Check if path is denied by config."""
        for denied in self.deny_paths:
            if denied in path or path.startswith(denied.replace("~", "")):
                return True, f"Path denied: {denied}"
        return False, ""

    def requires_pr(self, path: str) -> bool:
        """Check if path requires PR (no direct write)."""
        for pr_path in self.require_pr_paths:
            if pr_path.startswith("*."):
                # Extension match
                if path.endswith(pr_path[1:]):
                    return True
            elif pr_path in path or path.startswith(pr_path):
                return True
        return False


# Global gate config (set at startup, never changes)
GATE_CONFIG = GateConfig()


# ═══════════════════════════════════════════════════════════════════════════════
# BYLAW ENGINE v2
# ═══════════════════════════════════════════════════════════════════════════════

class BylawEngine:
    """
    Evaluates actions against bylaws to determine if they should proceed.

    v2 Features:
    - Role-based capability checking
    - Config-enforced gates (cannot be overridden)
    - PR-only workflow for code changes
    - Evidence bundle logging for every decision

    This is the core governance mechanism. It does NOT ask for permission -
    it makes autonomous decisions based on predefined rules.
    """

    def __init__(
        self,
        role: AgentRole = AgentRole.DEVELOPER,
        blocked_patterns: list[tuple[str, str]] | None = None,
        escalation_triggers: list[EscalationTrigger] | None = None,
        verification_config: VerificationConfig | None = None,
        gate_config: GateConfig | None = None,
    ):
        self.role = role
        self.capabilities = ROLE_CAPABILITIES[role]
        self.blocked_patterns = blocked_patterns or BLOCKED_PATTERNS
        self.escalation_triggers = escalation_triggers or ESCALATION_TRIGGERS
        self.verification = verification_config or VERIFICATION
        self.gates = gate_config or GATE_CONFIG

        # Evidence trail
        self.decision_log: list[dict] = []

        # Compile patterns for efficiency
        self._compiled_blocks = [
            (re.compile(pattern, re.IGNORECASE), reason)
            for pattern, reason in self.blocked_patterns
        ]
    
    def evaluate(
        self,
        command: str,
        context: dict[str, Any] | None = None,
        action_type: str = "unknown",
    ) -> BylawResult:
        """
        Evaluate a command against bylaws.

        Args:
            command: The command or action to evaluate
            context: Additional context (file paths, cost estimates, etc.)
            action_type: Type of action ("bash", "file_write", "api_call", etc.)

        Returns:
            BylawResult indicating what action to take
        """
        context = context or {}

        # Gate 0: Config-enforced gates (cannot be overridden)
        if action_type == "bash":
            is_denied, reason = self.gates.is_bash_denied(command)
            if is_denied:
                result = BylawResult(
                    action=BylawAction.BLOCK,
                    reason=f"Gate denied: {reason}",
                    matched_rule="gate_bash",
                    context={"command": command},
                )
                self._log_decision(result, command, context)
                return result

        # Gate 1: Role-based capability check
        capability_result = self._check_role_capability(action_type, context)
        if capability_result:
            self._log_decision(capability_result, command, context)
            return capability_result

        # Law 0: Check for absolute blocks
        for pattern, reason in self._compiled_blocks:
            if pattern.search(command):
                result = BylawResult(
                    action=BylawAction.BLOCK,
                    reason=f"Blocked by Law 0: {reason}",
                    matched_rule="blocked_patterns",
                    context={"pattern": pattern.pattern, "command": command},
                )
                self._log_decision(result, command, context)
                return result

        # Law 2: Check escalation triggers
        for trigger in self.escalation_triggers:
            if self._matches_trigger(command, trigger, context):
                result = BylawResult(
                    action=trigger.action,
                    reason=f"Triggered: {trigger.description}",
                    matched_rule=trigger.name,
                    context=context,
                )
                self._log_decision(result, command, context)
                return result

        # Gate 2: PR requirement for code paths
        filepath = context.get("filepath", "")
        if filepath and self.gates.requires_pr(filepath):
            if action_type == "file_write" and not self.capabilities.can_push_direct:
                result = BylawResult(
                    action=BylawAction.NOTIFY,
                    reason=f"Path requires PR: {filepath}",
                    matched_rule="require_pr",
                    context={"filepath": filepath, "suggestion": "Use create_pr instead"},
                )
                self._log_decision(result, command, context)
                return result

        # Law 1: Determine if verification needed
        if filepath and not self.verification.should_skip(filepath):
            result = BylawResult(
                action=BylawAction.VERIFY_FIRST,
                reason="Verification required before commit",
                matched_rule="verification",
                context={"filepath": filepath},
            )
            self._log_decision(result, command, context)
            return result

        # Default: proceed
        result = BylawResult(
            action=BylawAction.PROCEED,
            reason="No bylaw violations detected",
        )
        self._log_decision(result, command, context)
        return result

    def _check_role_capability(
        self, action_type: str, context: dict[str, Any]
    ) -> BylawResult | None:
        """Check if current role has capability for this action."""
        caps = self.capabilities

        # Map action types to capabilities
        capability_map = {
            "bash": caps.can_execute_bash,
            "python": caps.can_execute_python,
            "file_write": caps.can_write_files,
            "file_read": caps.can_read_files,
            "api_call": caps.can_make_api_calls,
            "database": caps.can_modify_database,
            "transact": caps.can_transact,
        }

        required_cap = capability_map.get(action_type)
        if required_cap is False:
            return BylawResult(
                action=BylawAction.BLOCK,
                reason=f"Role {self.role.value} cannot perform {action_type}",
                matched_rule="role_capability",
                context={"role": self.role.value, "action_type": action_type},
            )

        # Check cost limits
        cost = context.get("estimated_cost", 0)
        if cost > caps.max_cost_usd:
            return BylawResult(
                action=BylawAction.ESCALATE,
                reason=f"Cost ${cost:.2f} exceeds role limit ${caps.max_cost_usd:.2f}",
                matched_rule="cost_limit",
                context={"cost": cost, "limit": caps.max_cost_usd},
            )

        return None

    def _log_decision(
        self, result: BylawResult, command: str, context: dict[str, Any]
    ):
        """Log decision to evidence trail (in-memory + file)."""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "command": command[:200],  # Truncate long commands
            "action": result.action.value,
            "reason": result.reason,
            "rule": result.matched_rule,
            "role": self.role.value,
        }

        # In-memory log
        self.decision_log.append(log_entry)

        # Persist to logs/bylaws.jsonl
        _log_bylaw_decision(log_entry)
    
    def _matches_trigger(
        self,
        command: str,
        trigger: EscalationTrigger,
        context: dict[str, Any],
    ) -> bool:
        """Check if command matches an escalation trigger."""
        # Pattern matching
        for pattern in trigger.patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        
        # Threshold checking
        if trigger.threshold is not None:
            cost = context.get("estimated_cost", 0)
            if cost > trigger.threshold:
                return True
        
        # Condition checking (for complex conditions)
        if trigger.condition and trigger.condition in context:
            return bool(context[trigger.condition])
        
        return False
    
    def evaluate_file_change(
        self,
        filepath: str,
        change_type: str,  # "create", "modify", "delete"
        content: str | None = None,
    ) -> BylawResult:
        """Evaluate a file change operation."""
        context = {
            "filepath": filepath,
            "change_type": change_type,
        }
        
        # Check for dangerous file paths
        dangerous_paths = ["/etc/", "/usr/", "/bin/", "/sbin/", "~/.ssh/"]
        for dangerous in dangerous_paths:
            if filepath.startswith(dangerous) or f"/{dangerous}" in filepath:
                return BylawResult(
                    action=BylawAction.BLOCK,
                    reason=f"Cannot modify system path: {dangerous}",
                    matched_rule="system_protection",
                    context=context,
                )
        
        # Check content if provided
        if content:
            result = self.evaluate(content, context)
            if result.action == BylawAction.BLOCK:
                return result
        
        # Check if verification needed
        if not self.verification.should_skip(filepath):
            return BylawResult(
                action=BylawAction.VERIFY_FIRST,
                reason="File change requires verification",
                matched_rule="verification",
                context=context,
            )
        
        return BylawResult(
            action=BylawAction.PROCEED,
            reason="File change permitted",
            context=context,
        )


# Global engine instances (one per role)
_engines: dict[AgentRole, BylawEngine] = {}


def get_bylaw_engine(role: AgentRole = AgentRole.DEVELOPER) -> BylawEngine:
    """Get or create a bylaw engine for the specified role."""
    global _engines
    if role not in _engines:
        _engines[role] = BylawEngine(role=role)
    return _engines[role]


def get_observer_engine() -> BylawEngine:
    """Get engine for observer role (read-only)."""
    return get_bylaw_engine(AgentRole.OBSERVER)


def get_developer_engine() -> BylawEngine:
    """Get engine for developer role (code changes via PR)."""
    return get_bylaw_engine(AgentRole.DEVELOPER)


def get_executor_engine() -> BylawEngine:
    """Get engine for executor role (can transact, limited writes)."""
    return get_bylaw_engine(AgentRole.EXECUTOR)


# ═══════════════════════════════════════════════════════════════════════════════
# PERSONA BYLAW (5-Element Framework)
# Soft enforcement: NOTIFY for complex tasks without persona
# ═══════════════════════════════════════════════════════════════════════════════

class PersonaBylaw:
    """
    Bylaw: Complex tasks SHOULD use specific 5-element personas.

    This is a soft bylaw (NOTIFY, not BLOCK) that reminds the system
    when a complex task is being processed without a persona, which
    may result in lower quality output.

    Reference: https://reddit.com/r/PromptEngineering/comments/1oefkfe/
    """

    # Categories that warrant persona usage
    COMPLEX_CATEGORIES = [
        "architecture",
        "complex_architecture",
        "refactor",
        "multi_file_refactor",
        "critical",
        "critical_decisions",
    ]

    def evaluate(
        self,
        category: str,
        has_persona: bool,
    ) -> BylawResult:
        """
        Check if a complex task has an appropriate persona.

        Args:
            category: TaskCategory value
            has_persona: Whether a persona was selected

        Returns:
            BylawResult with NOTIFY if persona recommended but missing
        """
        is_complex = category.lower() in self.COMPLEX_CATEGORIES

        if is_complex and not has_persona:
            return BylawResult(
                action=BylawAction.NOTIFY,
                reason="Complex task without persona - output quality may degrade",
                matched_rule="persona_recommended",
                context={"category": category, "suggestion": "Consider adding domain-specific persona"},
            )

        return BylawResult(
            action=BylawAction.PROCEED,
            reason="Persona check passed",
            matched_rule="persona_check",
            context={"category": category, "has_persona": has_persona},
        )


# Global persona bylaw instance
_persona_bylaw = PersonaBylaw()


def check_persona_bylaw(category: str, has_persona: bool) -> BylawResult:
    """Convenience function to check persona bylaw."""
    return _persona_bylaw.evaluate(category, has_persona)
