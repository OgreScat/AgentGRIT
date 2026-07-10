"""
AgentGRIT Two-Stage Escalation System

Implements dual-authorization / two-person integrity for agent actions.

SECURITY MODEL:
- All external text (web, Telegram, scraped) is UNTRUSTED
- Approvals are for TYPED JSON actions only (no freeform commands)
- Manager can only approve/reject - cannot execute anything
- High-risk actions require Owner approval after Manager approval
- All secrets redacted from logs and messages

FLOW:
  Worker -> (ESCALATE) -> Manager -> (if high/critical) -> Owner -> Executor

LAWS:
  1. No silent privilege - escalated actions STOP until approved
  2. Typed actions only - approvals are for structured ActionRequest, not text
  3. Evidence before approval - Worker must attach evidence bundle
  4. Two-step for irreversible - trades/uploads/credentials need Manager + Owner
  5. Least privilege execution - approved actions run in sandbox
  6. Redaction always - secrets never appear in logs/messages
  7. Prompt injection is untrusted - external content cannot influence tool calls
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum, Enum
from pathlib import Path
from typing import Any, Callable

from ..security.redact import redact, redact_dict

# Late import to avoid circular dependency
# from .escalation_store import EscalationStore


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════════

class RiskLevel(IntEnum):
    """
    Risk classification for escalated actions.

    Using IntEnum so comparisons work correctly:
      RiskLevel.HIGH >= RiskLevel.MEDIUM  # True
    """
    LOW = 10           # Informational, reversible
    MEDIUM = 20        # Needs attention, usually reversible
    HIGH = 30          # Significant impact, hard to reverse
    CRITICAL = 40      # Irreversible, financial, security-impacting

    @property
    def label(self) -> str:
        """Human-readable label for display."""
        return self.name.lower()


class DeciderRole(Enum):
    """Who made the decision."""
    MANAGER = "manager"   # Internal approver agent
    OWNER = "owner"       # Human (you) via Telegram


class Decision(Enum):
    """Possible decisions on an escalation."""
    APPROVE = "approve"
    REJECT = "reject"
    MORE_INFO = "more_info"
    EXPIRED = "expired"   # TTL exceeded


class ActionCategory(Enum):
    """Categories of actions that can be escalated."""
    READ_ONLY = "read_only"           # Safe reads
    FILE_WRITE = "file_write"         # Write to filesystem
    SHELL_EXECUTE = "shell_execute"   # Run shell commands
    API_CALL = "api_call"             # External API calls
    TRADE = "trade"                   # Financial transactions
    UPLOAD = "upload"                 # Upload to external services
    CREDENTIAL_CHANGE = "credential_change"  # Modify secrets/auth
    DATABASE_WRITE = "database_write" # Modify database
    PUBLISH = "publish"               # Public content (social media, etc)


# Actions that ALWAYS require Owner approval (after Manager)
OWNER_REQUIRED_CATEGORIES = frozenset({
    ActionCategory.TRADE,
    ActionCategory.UPLOAD,
    ActionCategory.CREDENTIAL_CHANGE,
    ActionCategory.PUBLISH,
})

# Actions that require Owner if risk >= HIGH
OWNER_IF_HIGH_RISK = frozenset({
    ActionCategory.FILE_WRITE,
    ActionCategory.SHELL_EXECUTE,
    ActionCategory.DATABASE_WRITE,
})


# ═══════════════════════════════════════════════════════════════════════════════
# TYPED ACTION SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ActionRequest:
    """
    Typed action request - NOT freeform text.

    This is what gets approved, not arbitrary commands.
    The schema enforces structure and prevents prompt injection.
    """
    category: ActionCategory
    operation: str              # Specific operation within category
    parameters: dict[str, Any]  # Typed parameters for the operation

    # Safety metadata
    reversible: bool = True
    rollback_command: str | None = None
    estimated_cost_usd: float = 0.0
    affected_resources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "operation": self.operation,
            "parameters": redact_dict(self.parameters),
            "reversible": self.reversible,
            "rollback_command": self.rollback_command,
            "estimated_cost_usd": self.estimated_cost_usd,
            "affected_resources": self.affected_resources,
        }

    def signature(self) -> str:
        """Generate a fingerprint for deduplication."""
        content = f"{self.category.value}:{self.operation}:{sorted(self.parameters.keys())}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class EvidenceBundle:
    """
    Evidence that must accompany an escalation request.

    Worker MUST provide this - no approval without evidence.
    """
    # What triggered the escalation
    trigger_reason: str
    bylaw_matched: str | None = None

    # Context
    input_summary: str = ""           # Redacted summary of inputs
    simulation_result: str | None = None  # Dry-run output if applicable
    diff_preview: str | None = None   # File changes preview

    # References (paths, not content)
    log_refs: list[str] = field(default_factory=list)
    screenshot_refs: list[str] = field(default_factory=list)

    # Rollback
    rollback_plan: str | None = None
    rollback_tested: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_reason": self.trigger_reason,
            "bylaw_matched": self.bylaw_matched,
            "input_summary": redact(self.input_summary),
            "simulation_result": redact(self.simulation_result) if self.simulation_result else None,
            "diff_preview": self.diff_preview[:500] if self.diff_preview else None,
            "log_refs": self.log_refs[:5],
            "screenshot_refs": self.screenshot_refs[:3],
            "rollback_plan": self.rollback_plan,
            "rollback_tested": self.rollback_tested,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# ESCALATION REQUEST
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class EscalationRequest:
    """
    A request for approval of an action.

    Created when bylaws return ESCALATE or immunity blocks with override_required.
    """
    id: str                           # Unique ID (nonce)
    created_at: datetime
    requester: str                    # Agent/component that requested

    # The action being requested
    action: ActionRequest
    risk_level: RiskLevel

    # Evidence (required)
    evidence: EvidenceBundle

    # Lifecycle
    ttl_seconds: int = 300            # 5 minute default
    status: str = "pending"           # pending, decided, expired, cancelled

    # Decisions (filled as they happen)
    manager_decision: EscalationDecision | None = None
    owner_decision: EscalationDecision | None = None

    @property
    def expires_at(self) -> datetime:
        return self.created_at + timedelta(seconds=self.ttl_seconds)

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

    @property
    def requires_owner(self) -> bool:
        """Check if this escalation needs Owner approval."""
        # Always require Owner for certain categories
        if self.action.category in OWNER_REQUIRED_CATEGORIES:
            return True
        # Require Owner for high/critical risk in sensitive categories
        if self.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            if self.action.category in OWNER_IF_HIGH_RISK:
                return True
        return False

    @property
    def is_approved(self) -> bool:
        """Check if fully approved (Manager + Owner if required)."""
        if self.manager_decision is None:
            return False
        if self.manager_decision.decision != Decision.APPROVE:
            return False
        if self.requires_owner:
            if self.owner_decision is None:
                return False
            if self.owner_decision.decision != Decision.APPROVE:
                return False
        return True

    @property
    def is_rejected(self) -> bool:
        """Check if rejected at any stage."""
        if self.manager_decision and self.manager_decision.decision == Decision.REJECT:
            return True
        if self.owner_decision and self.owner_decision.decision == Decision.REJECT:
            return True
        return False

    @property
    def pending_stage(self) -> str:
        """What stage is pending?"""
        if self.is_expired:
            return "expired"
        if self.manager_decision is None:
            return "manager"
        if self.requires_owner and self.owner_decision is None:
            return "owner"
        return "complete"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "requester": self.requester,
            "action": self.action.to_dict(),
            "risk_level": self.risk_level.value,
            "evidence": self.evidence.to_dict(),
            "ttl_seconds": self.ttl_seconds,
            "status": self.status,
            "requires_owner": self.requires_owner,
            "pending_stage": self.pending_stage,
            "manager_decision": self.manager_decision.to_dict() if self.manager_decision else None,
            "owner_decision": self.owner_decision.to_dict() if self.owner_decision else None,
        }

    def to_telegram_summary(self) -> str:
        """Format for Telegram notification (redacted)."""
        risk_emoji = {
            RiskLevel.LOW: "🟢",
            RiskLevel.MEDIUM: "🟡",
            RiskLevel.HIGH: "🟠",
            RiskLevel.CRITICAL: "🔴",
        }

        lines = [
            f"⚠️ *ESCALATION REQUEST*",
            f"",
            f"ID: `{self.id}`",
            f"Risk: {risk_emoji.get(self.risk_level, '❓')} {self.risk_level.name}",
            f"Category: {self.action.category.value}",
            f"Operation: {self.action.operation}",
            f"",
            f"*Reason:* {self.evidence.trigger_reason[:100]}",
            f"",
            f"Expires: {self.expires_at.strftime('%H:%M:%S UTC')}",
            f"Stage: {self.pending_stage}",
        ]

        if self.requires_owner:
            lines.append(f"⚡ Requires OWNER approval")

        lines.extend([
            f"",
            f"Commands:",
            f"`/escalation approve {self.id}`",
            f"`/escalation reject {self.id}`",
            f"`/escalation show {self.id}`",
        ])

        return "\n".join(lines)


@dataclass
class EscalationDecision:
    """
    A decision made on an escalation.
    """
    id: str                   # References the EscalationRequest.id
    decided_at: datetime
    decider_role: DeciderRole
    decider_id: str           # Telegram user ID or "manager_agent"

    decision: Decision
    rationale: str            # Why this decision was made
    conditions: list[str] = field(default_factory=list)  # Any conditions attached

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "decided_at": self.decided_at.isoformat(),
            "decider_role": self.decider_role.value,
            "decider_id": self.decider_id,
            "decision": self.decision.value,
            "rationale": redact(self.rationale),
            "conditions": self.conditions,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# MANAGER APPROVER
# ═══════════════════════════════════════════════════════════════════════════════

class ManagerApprover:
    """
    Internal Manager approver with STRICT permissions.

    The Manager:
    - CAN: Inspect typed requests and evidence, approve/reject/request more info
    - CANNOT: Execute tools, run shell, trade, modify files, make API calls

    This is a deterministic rules-based approver, NOT an LLM.
    """

    # Checklist items the Manager verifies
    APPROVAL_CHECKLIST = [
        "evidence_present",      # Evidence bundle is not empty
        "rollback_plan_exists",  # For non-reversible actions
        "risk_matches_action",   # Risk level appropriate for action type
        "not_blocked_pattern",   # Action doesn't match blocked patterns
        "within_cost_limit",     # Estimated cost within threshold
        "ttl_valid",             # Request not expired
    ]

    # Patterns that Manager will ALWAYS reject
    BLOCKED_PATTERNS = [
        "rm -rf",
        "DROP TABLE",
        "DROP DATABASE",
        "--force",
        "sudo",
        "chmod 777",
        "curl | sh",
        "eval(",
    ]

    # Cost thresholds per risk level
    COST_LIMITS = {
        RiskLevel.LOW: 0.10,
        RiskLevel.MEDIUM: 1.00,
        RiskLevel.HIGH: 10.00,
        RiskLevel.CRITICAL: 100.00,
    }

    def __init__(self):
        self.decisions: list[EscalationDecision] = []

    def evaluate(self, request: EscalationRequest) -> EscalationDecision:
        """
        Evaluate an escalation request.

        Returns a decision (approve/reject/more_info).
        Manager CANNOT execute anything - only decide.
        """
        checks_passed = []
        checks_failed = []

        # 1. Evidence present
        if request.evidence.trigger_reason:
            checks_passed.append("evidence_present")
        else:
            checks_failed.append("evidence_present: No trigger reason provided")

        # 2. Rollback plan for non-reversible
        if not request.action.reversible:
            if request.evidence.rollback_plan:
                checks_passed.append("rollback_plan_exists")
            else:
                checks_failed.append("rollback_plan_exists: Non-reversible action needs rollback plan")
        else:
            checks_passed.append("rollback_plan_exists")

        # 3. Risk matches action
        min_risk = self._minimum_risk_for_action(request.action)
        # IntEnum comparison works correctly now (e.g., HIGH >= MEDIUM is True)
        if request.risk_level >= min_risk:
            checks_passed.append("risk_matches_action")
        else:
            checks_failed.append(f"risk_matches_action: {request.action.category.value} requires at least {min_risk.name}")

        # 4. Blocked patterns
        action_str = json.dumps(request.action.to_dict()).lower()
        blocked = [p for p in self.BLOCKED_PATTERNS if p.lower() in action_str]
        if blocked:
            checks_failed.append(f"not_blocked_pattern: Contains {blocked}")
        else:
            checks_passed.append("not_blocked_pattern")

        # 5. Cost limit
        limit = self.COST_LIMITS.get(request.risk_level, 0)
        if request.action.estimated_cost_usd <= limit:
            checks_passed.append("within_cost_limit")
        else:
            checks_failed.append(f"within_cost_limit: ${request.action.estimated_cost_usd} > ${limit} for {request.risk_level.name}")

        # 6. TTL valid
        if not request.is_expired:
            checks_passed.append("ttl_valid")
        else:
            checks_failed.append("ttl_valid: Request has expired")

        # Make decision
        if checks_failed:
            if "ttl_valid" in str(checks_failed):
                decision = Decision.EXPIRED
            elif len(checks_failed) == 1 and "evidence" in str(checks_failed[0]):
                decision = Decision.MORE_INFO
            else:
                decision = Decision.REJECT
            rationale = f"Failed checks: {'; '.join(checks_failed)}"
        else:
            decision = Decision.APPROVE
            rationale = f"All checks passed: {', '.join(checks_passed)}"

        result = EscalationDecision(
            id=request.id,
            decided_at=datetime.utcnow(),
            decider_role=DeciderRole.MANAGER,
            decider_id="manager_agent",
            decision=decision,
            rationale=rationale,
            conditions=[],
        )

        self.decisions.append(result)
        return result

    def _minimum_risk_for_action(self, action: ActionRequest) -> RiskLevel:
        """Determine minimum risk level for an action category."""
        if action.category in OWNER_REQUIRED_CATEGORIES:
            return RiskLevel.HIGH
        if action.category in (ActionCategory.FILE_WRITE, ActionCategory.DATABASE_WRITE):
            return RiskLevel.MEDIUM
        if action.category == ActionCategory.SHELL_EXECUTE:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW


# ═══════════════════════════════════════════════════════════════════════════════
# ESCALATION MANAGER (Orchestrator)
# ═══════════════════════════════════════════════════════════════════════════════

class EscalationManager:
    """
    Central manager for the escalation workflow.

    Handles:
    - Creating escalation requests
    - Routing to Manager approver
    - Routing to Owner (via Telegram)
    - Logging all events
    - Expiring stale requests
    - SQLite persistence (survives restarts)
    """

    def __init__(
        self,
        log_dir: Path = Path("logs"),
        owner_telegram_ids: list[int] | None = None,
        breakglass_telegram_ids: list[int] | None = None,
        db_path: Path | None = None,
    ):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = log_dir / "escalations.jsonl"

        # Allowlisted Telegram IDs
        self.owner_ids = set(owner_telegram_ids or [])
        self.breakglass_ids = set(breakglass_telegram_ids or [])  # Can only /stop, /status

        # SQLite persistence (CRITICAL: survives restarts)
        from .escalation_store import EscalationStore
        self.store = EscalationStore(db_path or Path("data/escalations.db"))

        # State - load from SQLite on startup
        self.pending: dict[str, EscalationRequest] = {}
        self.completed: dict[str, EscalationRequest] = {}
        self.manager = ManagerApprover()

        # Restore pending escalations from disk
        self._restore_from_store()

        # Callbacks
        self._notify_callback: Callable[[str], None] | None = None

    def _restore_from_store(self):
        """Restore pending escalations from SQLite on startup."""
        # First, expire any stale ones in the database
        expired_count = self.store.expire_stale()
        if expired_count > 0:
            self._log_event("startup_expired_stale", {"count": expired_count})

        # Load pending escalations
        pending = self.store.load_pending()
        for request in pending:
            self.pending[request.id] = request

        if pending:
            self._log_event("startup_restored", {
                "pending_count": len(pending),
                "ids": [r.id for r in pending],
            })

    def set_notify_callback(self, callback: Callable[[str], None]):
        """Set callback for sending Telegram notifications."""
        self._notify_callback = callback

    def create_escalation(
        self,
        requester: str,
        action: ActionRequest,
        risk_level: RiskLevel,
        evidence: EvidenceBundle,
        ttl_seconds: int = 300,
    ) -> EscalationRequest:
        """
        Create a new escalation request.

        This STOPS execution until approved.
        """
        # Generate unique ID (nonce)
        nonce = secrets.token_urlsafe(8)

        request = EscalationRequest(
            id=nonce,
            created_at=datetime.utcnow(),
            requester=requester,
            action=action,
            risk_level=risk_level,
            evidence=evidence,
            ttl_seconds=ttl_seconds,
        )

        self.pending[nonce] = request

        # Log creation
        self._log_event("escalation_created", {
            "id": nonce,
            "requester": requester,
            "category": action.category.value,
            "risk_level": risk_level.value,
            "requires_owner": request.requires_owner,
            "expires_at": request.expires_at.isoformat(),
        })

        # Auto-evaluate with Manager
        manager_decision = self.manager.evaluate(request)
        request.manager_decision = manager_decision

        self._log_event("manager_decision", {
            "id": nonce,
            "decision": manager_decision.decision.value,
            "rationale": manager_decision.rationale,
        })

        # If Manager approved and needs Owner, notify
        if manager_decision.decision == Decision.APPROVE and request.requires_owner:
            if self._notify_callback:
                self._notify_callback(request.to_telegram_summary())

        # If Manager rejected, move to completed
        if manager_decision.decision in (Decision.REJECT, Decision.EXPIRED):
            request.status = "decided"
            self.completed[nonce] = self.pending.pop(nonce)
        # If Manager approved and no Owner needed, also move to completed
        elif manager_decision.decision == Decision.APPROVE and not request.requires_owner:
            request.status = "decided"
            self.completed[nonce] = self.pending.pop(nonce)

        # CRITICAL: Persist to SQLite (survives restarts)
        self.store.save_escalation(request)

        return request

    def owner_decide(
        self,
        escalation_id: str,
        decision: Decision,
        rationale: str,
        decider_telegram_id: int,
    ) -> EscalationDecision | None:
        """
        Record Owner's decision on an escalation.

        Only allowed from allowlisted Telegram IDs.
        """
        # Verify authorization
        if decider_telegram_id not in self.owner_ids:
            self._log_event("unauthorized_decision_attempt", {
                "id": escalation_id,
                "telegram_id": decider_telegram_id,
            })
            return None

        # Find the request
        request = self.pending.get(escalation_id)
        if not request:
            return None

        # Check expiry
        if request.is_expired:
            request.status = "expired"
            self.completed[escalation_id] = self.pending.pop(escalation_id)
            # Persist expiry to SQLite
            self.store.mark_resolved(escalation_id, "expired")
            return None

        # Record decision
        owner_decision = EscalationDecision(
            id=escalation_id,
            decided_at=datetime.utcnow(),
            decider_role=DeciderRole.OWNER,
            decider_id=str(decider_telegram_id),
            decision=decision,
            rationale=rationale,
        )

        request.owner_decision = owner_decision
        request.status = "decided"

        self._log_event("owner_decision", {
            "id": escalation_id,
            "decision": decision.value,
            "rationale": redact(rationale),
            "decider_id": str(decider_telegram_id),
        })

        # Move to completed
        self.completed[escalation_id] = self.pending.pop(escalation_id)

        # CRITICAL: Persist decision to SQLite (survives restarts)
        self.store.save_escalation(request)

        return owner_decision

    def get_pending(self) -> list[EscalationRequest]:
        """Get all pending escalations."""
        # First, expire any stale ones
        self._expire_stale()
        return list(self.pending.values())

    def get_request(self, escalation_id: str) -> EscalationRequest | None:
        """Get a specific escalation request."""
        return self.pending.get(escalation_id) or self.completed.get(escalation_id)

    def is_owner(self, telegram_id: int) -> bool:
        """Check if Telegram ID is an Owner."""
        return telegram_id in self.owner_ids

    def is_breakglass(self, telegram_id: int) -> bool:
        """Check if Telegram ID is break-glass admin."""
        return telegram_id in self.breakglass_ids

    def get_stats(self) -> dict[str, Any]:
        """Get escalation statistics from SQLite store."""
        return self.store.get_stats()

    def get_history(self, limit: int = 100) -> list[EscalationRequest]:
        """Get escalation history (all escalations, not just pending)."""
        return self.store.load_all(limit=limit)

    def _expire_stale(self):
        """Expire any requests past TTL."""
        now = datetime.utcnow()
        expired = []

        for eid, request in self.pending.items():
            if request.is_expired:
                request.status = "expired"
                self._log_event("escalation_expired", {"id": eid})
                expired.append(eid)

        for eid in expired:
            self.completed[eid] = self.pending.pop(eid)
            # Persist expiry to SQLite
            self.store.mark_resolved(eid, "expired")

    def _log_event(self, event: str, data: dict[str, Any]):
        """Append event to JSONL log."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "event": event,
            "data": redact_dict(data),
        }

        with open(self.log_file, "a") as f:
            json.dump(entry, f)
            f.write("\n")


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTION TOKEN (Separate from Escalation ID)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ExecutionToken:
    """
    One-time execution authorization token.

    CRITICAL: This is SEPARATE from the EscalationRequest.id.
    - Escalation ID = tracks the approval workflow
    - Execution Token = authorizes a single execution attempt

    The token is:
    - Minted ONLY after full approval (Manager + Owner if required)
    - Bound to specific action signature
    - Single-use (consumed on execution)
    - Time-limited (expires independently of escalation)
    """
    token: str                    # Cryptographically random token
    escalation_id: str            # Link to the approval
    action_signature: str         # Hash of canonical ActionRequest
    minted_at: datetime
    expires_at: datetime
    max_uses: int = 1
    uses_remaining: int = 1
    consumed: bool = False
    consumed_at: datetime | None = None

    def is_valid(self) -> bool:
        """Check if token is still valid."""
        if self.consumed:
            return False
        if self.uses_remaining <= 0:
            return False
        if datetime.utcnow() > self.expires_at:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "token": self.token,
            "escalation_id": self.escalation_id,
            "action_signature": self.action_signature,
            "minted_at": self.minted_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "max_uses": self.max_uses,
            "uses_remaining": self.uses_remaining,
            "consumed": self.consumed,
            "consumed_at": self.consumed_at.isoformat() if self.consumed_at else None,
        }


class ExecutionTokenManager:
    """
    Manages one-time execution tokens.

    SECURITY:
    - Tokens are only minted for FULLY APPROVED escalations
    - Each token is bound to a specific action signature
    - Replay is impossible (single-use, marked consumed)
    """

    def __init__(self, log_file: Path | None = None):
        self.tokens: dict[str, ExecutionToken] = {}
        self.log_file = log_file

    def mint_token(
        self,
        escalation: EscalationRequest,
        ttl_seconds: int = 60,
    ) -> ExecutionToken | None:
        """
        Mint a one-time execution token for an approved escalation.

        CRITICAL INVARIANTS (checked at execute-time, not just approve-time):
        1. Escalation must be fully approved (Manager + Owner if required)
        2. Escalation must NOT be expired (TTL checked HERE at mint-time)
        3. For OWNER_REQUIRED categories, Owner decision must exist

        Returns None if any invariant fails.
        """
        # INVARIANT 1: Must be approved
        if not escalation.is_approved:
            self._log_event("token_denied", {
                "escalation_id": escalation.id,
                "reason": "not_approved",
            })
            return None

        # INVARIANT 2: TTL check at execute-time (not just approve-time)
        # This prevents "approve now, execute later after TTL" attacks
        if escalation.is_expired:
            self._log_event("token_denied", {
                "escalation_id": escalation.id,
                "reason": "expired_at_mint_time",
                "expired_at": escalation.expires_at.isoformat(),
            })
            return None

        # INVARIANT 3: Owner decision required for sensitive categories
        if escalation.requires_owner and escalation.owner_decision is None:
            self._log_event("token_denied", {
                "escalation_id": escalation.id,
                "reason": "owner_decision_missing",
                "category": escalation.action.category.value,
            })
            return None

        # Generate cryptographically random token
        token_value = secrets.token_urlsafe(32)

        # Generate action signature (hash of canonical action)
        action_canonical = json.dumps(escalation.action.to_dict(), sort_keys=True)
        action_sig = hashlib.sha256(action_canonical.encode()).hexdigest()

        token = ExecutionToken(
            token=token_value,
            escalation_id=escalation.id,
            action_signature=action_sig,
            minted_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(seconds=ttl_seconds),
            max_uses=1,
            uses_remaining=1,
        )

        self.tokens[token_value] = token

        self._log_event("token_minted", {
            "token": token_value[:8] + "...",  # Redact most of token
            "escalation_id": escalation.id,
            "action_signature": action_sig[:16],
            "expires_at": token.expires_at.isoformat(),
        })

        return token

    def validate_and_consume(
        self,
        token_value: str,
        action: ActionRequest,
    ) -> tuple[bool, str]:
        """
        Validate a token against an action and consume it.

        Returns (valid, reason).
        """
        token = self.tokens.get(token_value)

        if not token:
            return False, "Token not found"

        if not token.is_valid():
            if token.consumed:
                return False, "Token already consumed (replay attempt blocked)"
            if token.uses_remaining <= 0:
                return False, "Token exhausted"
            return False, "Token expired"

        # Verify action signature matches
        action_canonical = json.dumps(action.to_dict(), sort_keys=True)
        action_sig = hashlib.sha256(action_canonical.encode()).hexdigest()

        if action_sig != token.action_signature:
            self._log_event("token_signature_mismatch", {
                "token": token_value[:8] + "...",
                "expected_sig": token.action_signature[:16],
                "actual_sig": action_sig[:16],
            })
            return False, "Action signature mismatch (tampering detected)"

        # Consume the token
        token.uses_remaining -= 1
        if token.uses_remaining <= 0:
            token.consumed = True
            token.consumed_at = datetime.utcnow()

        self._log_event("token_consumed", {
            "token": token_value[:8] + "...",
            "escalation_id": token.escalation_id,
            "consumed_at": token.consumed_at.isoformat() if token.consumed_at else None,
        })

        return True, "Token valid, execution authorized"

    def cleanup_expired(self):
        """Remove expired tokens."""
        now = datetime.utcnow()
        expired = [t for t, tok in self.tokens.items() if now > tok.expires_at]
        for t in expired:
            del self.tokens[t]

    def _log_event(self, event: str, data: dict[str, Any]):
        """Log token events."""
        if not self.log_file:
            return

        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "event": f"execution_token:{event}",
            "data": data,
        }

        with open(self.log_file, "a") as f:
            json.dump(entry, f)
            f.write("\n")


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def create_escalation_from_bylaw(
    manager: EscalationManager,
    bylaw_result,  # BylawResult from bylaws.py
    requester: str,
    action_category: ActionCategory,
    operation: str,
    parameters: dict[str, Any],
    estimated_cost: float = 0.0,
) -> EscalationRequest:
    """
    Helper to create an escalation from a bylaw ESCALATE result.
    """
    # Build evidence from bylaw context
    evidence = EvidenceBundle(
        trigger_reason=bylaw_result.reason,
        bylaw_matched=bylaw_result.matched_rule,
        input_summary=json.dumps(parameters)[:200],
    )

    # Build typed action
    action = ActionRequest(
        category=action_category,
        operation=operation,
        parameters=parameters,
        estimated_cost_usd=estimated_cost,
    )

    # Determine risk level from bylaw context
    risk_level = RiskLevel.MEDIUM
    if action_category in OWNER_REQUIRED_CATEGORIES:
        risk_level = RiskLevel.HIGH
    if "security" in bylaw_result.reason.lower():
        risk_level = RiskLevel.HIGH
    if "production" in bylaw_result.reason.lower():
        risk_level = RiskLevel.CRITICAL

    return manager.create_escalation(
        requester=requester,
        action=action,
        risk_level=risk_level,
        evidence=evidence,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = [
    # Enums
    "RiskLevel",
    "DeciderRole",
    "Decision",
    "ActionCategory",
    # Types
    "ActionRequest",
    "EvidenceBundle",
    "EscalationRequest",
    "EscalationDecision",
    "ExecutionToken",
    # Managers
    "ManagerApprover",
    "EscalationManager",
    "ExecutionTokenManager",
    # Helpers
    "create_escalation_from_bylaw",
    # Constants
    "OWNER_REQUIRED_CATEGORIES",
    "OWNER_IF_HIGH_RISK",
]
