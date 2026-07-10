"""
Hardened Telegram Bot Interface

SECURITY REQUIREMENTS:
1. Only accept commands from TELEGRAM_ADMIN_IDS (exact match)
2. Command grammar only - NO natural language task spawning
3. All write/trade/upload actions require /approve <nonce>
4. Rate limiting per user and global
5. LLM output treated as untrusted text - deterministic parser only
6. Two-stage escalation: Manager -> Owner approval for high-risk actions
7. Break-glass admin can only /stop and /status (no approvals)

ESCALATION FLOW:
  Worker -> (ESCALATE) -> Manager (auto) -> Owner (you via /escalation approve)
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set

from ..security.redact import redact, safe_log
from ..governance.escalations import (
    EscalationManager, EscalationRequest, Decision, DeciderRole
)


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SecurityConfig:
    """Hardened security configuration."""
    # Rate limiting
    commands_per_minute: int = 10
    burst_limit: int = 5
    cooldown_seconds: int = 60

    # Approval system
    nonce_expiry_seconds: int = 300  # 5 minutes
    max_pending_approvals: int = 10

    # Allowed commands (whitelist)
    allowed_commands: Set[str] = field(default_factory=lambda: {
        'start', 'help', 'status', 'digest', 'approve', 'run', 'set', 'logs',
        'escalation', 'escalations', 'stop'  # Escalation commands
    })

    # Allowed job names for /run
    allowed_jobs: Set[str] = field(default_factory=lambda: {
        'digest_now', 'health_check'
    })

    # Allowed config keys for /set
    allowed_config_keys: Set[str] = field(default_factory=lambda: {
        'dry_run', 'log_level', 'digest_interval'
    })

    # Break-glass admin commands (limited subset)
    breakglass_commands: Set[str] = field(default_factory=lambda: {
        'stop', 'status', 'escalations', 'help'
    })


# ═══════════════════════════════════════════════════════════════════════════════
# RATE LIMITER
# ═══════════════════════════════════════════════════════════════════════════════

class RateLimiter:
    """Token bucket rate limiter."""

    def __init__(self, rate: int, burst: int):
        self.rate = rate  # refill per minute
        self.burst = burst
        self.tokens: Dict[int, float] = defaultdict(lambda: burst)
        self.last_refill: Dict[int, float] = defaultdict(time.time)

    def check(self, user_id: int) -> bool:
        """Check if user can proceed. Returns True if allowed."""
        now = time.time()

        # Refill tokens
        elapsed = now - self.last_refill[user_id]
        refill = (elapsed / 60) * self.rate
        self.tokens[user_id] = min(self.burst, self.tokens[user_id] + refill)
        self.last_refill[user_id] = now

        # Check and consume
        if self.tokens[user_id] >= 1:
            self.tokens[user_id] -= 1
            return True
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# APPROVAL SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PendingApproval:
    """A pending action requiring approval."""
    nonce: str
    action: str
    params: Dict
    created_at: float
    expires_at: float


class ApprovalManager:
    """Manages pending approvals with time-limited nonces."""

    def __init__(self, config: SecurityConfig):
        self.config = config
        self.pending: Dict[str, PendingApproval] = {}

    def create(self, action: str, params: Dict) -> str:
        """Create a new approval request, return nonce."""
        # Cleanup expired
        self._cleanup()

        # Check limit
        if len(self.pending) >= self.config.max_pending_approvals:
            raise ValueError("Too many pending approvals")

        # Generate nonce
        nonce = secrets.token_hex(8)
        now = time.time()

        self.pending[nonce] = PendingApproval(
            nonce=nonce,
            action=action,
            params=params,
            created_at=now,
            expires_at=now + self.config.nonce_expiry_seconds
        )

        return nonce

    def approve(self, nonce: str) -> Optional[PendingApproval]:
        """Approve an action by nonce. Returns the action if valid."""
        self._cleanup()

        if nonce not in self.pending:
            return None

        approval = self.pending.pop(nonce)

        if time.time() > approval.expires_at:
            return None

        return approval

    def _cleanup(self):
        """Remove expired approvals."""
        now = time.time()
        expired = [k for k, v in self.pending.items() if now > v.expires_at]
        for k in expired:
            del self.pending[k]


# ═══════════════════════════════════════════════════════════════════════════════
# COMMAND PARSER (Deterministic, no LLM)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ParsedCommand:
    """Result of parsing a command."""
    command: str
    args: List[str]
    raw: str
    valid: bool
    error: Optional[str] = None


def parse_command(text: str, config: SecurityConfig) -> ParsedCommand:
    """
    Parse a command string. DETERMINISTIC - no LLM involvement.

    Supported formats:
        /status
        /digest
        /approve <nonce>
        /run <job>
        /set <key> <value>
        /logs [count]
    """
    text = text.strip()

    if not text.startswith('/'):
        return ParsedCommand(
            command='', args=[], raw=text, valid=False,
            error="Commands must start with /"
        )

    parts = text[1:].split()
    if not parts:
        return ParsedCommand(
            command='', args=[], raw=text, valid=False,
            error="Empty command"
        )

    command = parts[0].lower()
    args = parts[1:]

    # Whitelist check
    if command not in config.allowed_commands:
        return ParsedCommand(
            command=command, args=args, raw=text, valid=False,
            error=f"Unknown command: /{command}"
        )

    # Validate args for specific commands
    if command == 'approve' and len(args) != 1:
        return ParsedCommand(
            command=command, args=args, raw=text, valid=False,
            error="Usage: /approve <nonce>"
        )

    if command == 'run':
        if len(args) != 1:
            return ParsedCommand(
                command=command, args=args, raw=text, valid=False,
                error="Usage: /run <job>"
            )
        if args[0] not in config.allowed_jobs:
            return ParsedCommand(
                command=command, args=args, raw=text, valid=False,
                error=f"Unknown job: {args[0]}. Allowed: {', '.join(config.allowed_jobs)}"
            )

    if command == 'set':
        if len(args) < 2:
            return ParsedCommand(
                command=command, args=args, raw=text, valid=False,
                error="Usage: /set <key> <value>"
            )
        if args[0] not in config.allowed_config_keys:
            return ParsedCommand(
                command=command, args=args, raw=text, valid=False,
                error=f"Unknown config key: {args[0]}. Allowed: {', '.join(config.allowed_config_keys)}"
            )

    return ParsedCommand(
        command=command, args=args, raw=text, valid=True
    )


# ═══════════════════════════════════════════════════════════════════════════════
# HARDENED BOT
# ═══════════════════════════════════════════════════════════════════════════════

class HardenedTelegramBot:
    """
    Security-hardened Telegram bot with two-stage escalation.

    NEVER executes LLM output directly.
    NEVER spawns tasks from natural language.
    ALWAYS requires approval for dangerous actions.
    TWO-STAGE escalation: Manager (auto) -> Owner (you) for high-risk.
    """

    def __init__(self, config: Optional[SecurityConfig] = None):
        self.config = config or SecurityConfig()

        # Load admin IDs from env (Owner - full access)
        admin_str = os.getenv('TELEGRAM_ADMIN_IDS', '')
        self.admin_ids: Set[int] = set()
        for id_str in admin_str.split(','):
            id_str = id_str.strip()
            if id_str and id_str.isdigit():
                self.admin_ids.add(int(id_str))

        if not self.admin_ids:
            raise ValueError("TELEGRAM_ADMIN_IDS not configured or invalid")

        # Load break-glass admin IDs (limited access)
        breakglass_str = os.getenv('TELEGRAM_BREAKGLASS_IDS', '')
        self.breakglass_ids: Set[int] = set()
        for id_str in breakglass_str.split(','):
            id_str = id_str.strip()
            if id_str and id_str.isdigit():
                self.breakglass_ids.add(int(id_str))

        self.token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        if not self.token or self.token.startswith('ROTATE_ME'):
            raise ValueError("TELEGRAM_BOT_TOKEN not configured")

        self.rate_limiter = RateLimiter(
            rate=self.config.commands_per_minute,
            burst=self.config.burst_limit
        )
        self.approvals = ApprovalManager(self.config)

        # Initialize escalation manager
        from pathlib import Path
        self.escalation_manager = EscalationManager(
            log_dir=Path(os.getenv('LOG_DIR', './logs')),
            owner_telegram_ids=list(self.admin_ids),
            breakglass_telegram_ids=list(self.breakglass_ids),
        )

        # Command handlers
        self._handlers: Dict[str, Callable] = {
            'start': self._handle_start,
            'help': self._handle_help,
            'status': self._handle_status,
            'digest': self._handle_digest,
            'approve': self._handle_approve,
            'run': self._handle_run,
            'set': self._handle_set,
            'logs': self._handle_logs,
            'escalation': self._handle_escalation,
            'escalations': self._handle_escalations,
            'stop': self._handle_stop,
        }

        self._running = False
        self._stop_callback: Optional[Callable] = None

    def set_stop_callback(self, callback: Callable):
        """Set callback for /stop command."""
        self._stop_callback = callback

    def is_owner(self, user_id: int) -> bool:
        """Check if user is an Owner (full access)."""
        return user_id in self.admin_ids

    def is_breakglass(self, user_id: int) -> bool:
        """Check if user is break-glass admin (limited access)."""
        return user_id in self.breakglass_ids

    def is_authorized(self, user_id: int) -> bool:
        """Check if user is in any admin list."""
        return self.is_owner(user_id) or self.is_breakglass(user_id)

    async def handle_message(self, user_id: int, text: str) -> str:
        """
        Handle incoming message. Returns response text.

        This is the ONLY entry point for user input.
        """
        # Auth check - silent drop for non-admins
        if not self.is_authorized(user_id):
            # Log the attempt but don't respond
            print(f"[Security] Unauthorized access attempt from user {user_id}")
            return ""  # No response

        # Rate limit
        if not self.rate_limiter.check(user_id):
            return "Rate limited. Please wait."

        # Parse command
        parsed = parse_command(text, self.config)

        if not parsed.valid:
            return f"Error: {parsed.error}\n\nUse /help for available commands."

        # Break-glass admin can only use limited commands
        if self.is_breakglass(user_id) and not self.is_owner(user_id):
            if parsed.command not in self.config.breakglass_commands:
                return f"Break-glass admin cannot use /{parsed.command}. Allowed: {', '.join(self.config.breakglass_commands)}"

        # Execute handler
        handler = self._handlers.get(parsed.command)
        if handler:
            try:
                return await handler(parsed, user_id)
            except Exception as e:
                # Redact any secrets in error messages
                return f"Error: {safe_log(str(e))}"

        return f"No handler for /{parsed.command}"

    # ═══════════════════════════════════════════════════════════════════════════
    # COMMAND HANDLERS
    # ═══════════════════════════════════════════════════════════════════════════

    async def _handle_start(self, cmd: ParsedCommand, user_id: int) -> str:
        return (
            "AgentGRIT Hardened Interface\n\n"
            "Commands:\n"
            "/status - System status\n"
            "/escalations - List pending escalations\n"
            "/escalation show <id> - Show escalation details\n"
            "/escalation approve <id> - Approve escalation\n"
            "/escalation reject <id> - Reject escalation\n"
            "/run <job> - Run allowed job\n"
            "/stop - Stop all agents\n"
            "/logs [n] - View last n log lines\n"
            "/help - Show this message"
        )

    async def _handle_help(self, cmd: ParsedCommand, user_id: int) -> str:
        jobs = ', '.join(self.config.allowed_jobs)
        keys = ', '.join(self.config.allowed_config_keys)
        return (
            "Available Commands:\n\n"
            "ESCALATIONS:\n"
            "/escalations - List pending escalations\n"
            "/escalation show <id> - Show details\n"
            "/escalation approve <id> - Approve (Owner only)\n"
            "/escalation reject <id> - Reject (Owner only)\n\n"
            "OPERATIONS:\n"
            "/status - Current system status\n"
            f"/run <job> - Jobs: {jobs}\n"
            f"/set <key> <value> - Keys: {keys}\n"
            "/stop - Stop all agents\n"
            "/logs [n] - Last n log lines (default 10)\n\n"
            "Two-stage approval: Manager (auto) -> Owner (you)"
        )

    async def _handle_status(self, cmd: ParsedCommand, user_id: int) -> str:
        # Safe status - no secrets
        from pathlib import Path
        log_dir = Path(os.getenv('LOG_DIR', './logs'))

        # Count log entries
        log_counts = {}
        for log_file in log_dir.glob('*.jsonl'):
            try:
                with open(log_file) as f:
                    log_counts[log_file.stem] = sum(1 for _ in f)
            except:
                log_counts[log_file.stem] = 0

        # Get pending escalations
        pending = self.escalation_manager.get_pending()

        status_lines = [
            "System Status",
            "=" * 30,
            f"Dry Run: {os.getenv('DRY_RUN', 'true')}",
            f"Log Level: {os.getenv('LOG_LEVEL', 'INFO')}",
            f"Pending Escalations: {len(pending)}",
            "",
            "Log Entries:",
        ]
        for name, count in sorted(log_counts.items()):
            status_lines.append(f"  {name}: {count}")

        return "\n".join(status_lines)

    async def _handle_digest(self, cmd: ParsedCommand, user_id: int) -> str:
        return "Digest generation not implemented in hardened mode."

    async def _handle_approve(self, cmd: ParsedCommand, user_id: int) -> str:
        nonce = cmd.args[0]
        approval = self.approvals.approve(nonce)

        if not approval:
            return "Invalid or expired nonce."

        # Execute the approved action
        return f"Approved: {approval.action}\nParams: {redact(str(approval.params))}"

    async def _handle_run(self, cmd: ParsedCommand, user_id: int) -> str:
        job = cmd.args[0]

        # Create approval requirement for jobs
        nonce = self.approvals.create('run_job', {'job': job})

        return (
            f"Job '{job}' requires approval.\n\n"
            f"To confirm, send:\n/approve {nonce}\n\n"
            f"Expires in {self.config.nonce_expiry_seconds // 60} minutes."
        )

    async def _handle_set(self, cmd: ParsedCommand, user_id: int) -> str:
        key = cmd.args[0]
        value = ' '.join(cmd.args[1:])

        # Create approval for config changes
        nonce = self.approvals.create('set_config', {'key': key, 'value': value})

        return (
            f"Config change requires approval.\n"
            f"Key: {key}\n"
            f"Value: {value}\n\n"
            f"To confirm, send:\n/approve {nonce}\n\n"
            f"Expires in {self.config.nonce_expiry_seconds // 60} minutes."
        )

    async def _handle_logs(self, cmd: ParsedCommand, user_id: int) -> str:
        count = 10
        if cmd.args:
            try:
                count = min(int(cmd.args[0]), 50)  # Cap at 50
            except ValueError:
                pass

        from pathlib import Path
        log_file = Path(os.getenv('LOG_DIR', './logs')) / 'bylaws.jsonl'

        if not log_file.exists():
            return "No logs found."

        try:
            with open(log_file) as f:
                lines = f.readlines()[-count:]

            # Redact all output
            return "Last {} log entries:\n\n{}".format(
                len(lines),
                safe_log('\n'.join(line.strip() for line in lines))
            )
        except Exception as e:
            return f"Error reading logs: {safe_log(str(e))}"

    # ═══════════════════════════════════════════════════════════════════════════
    # ESCALATION HANDLERS
    # ═══════════════════════════════════════════════════════════════════════════

    async def _handle_escalations(self, cmd: ParsedCommand, user_id: int) -> str:
        """List all pending escalations."""
        pending = self.escalation_manager.get_pending()

        if not pending:
            return "No pending escalations."

        lines = ["Pending Escalations:", "=" * 30]
        for esc in pending:
            risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}
            emoji = risk_emoji.get(esc.risk_level.value, "❓")
            lines.append(
                f"\n{emoji} `{esc.id}`\n"
                f"   Category: {esc.action.category.value}\n"
                f"   Stage: {esc.pending_stage}\n"
                f"   Expires: {esc.expires_at.strftime('%H:%M:%S')}"
            )

        lines.append("\nUse /escalation show <id> for details")
        return "\n".join(lines)

    async def _handle_escalation(self, cmd: ParsedCommand, user_id: int) -> str:
        """Handle escalation subcommands: show, approve, reject, moreinfo."""
        if not cmd.args:
            return "Usage: /escalation <show|approve|reject|moreinfo> <id>"

        subcommand = cmd.args[0].lower()

        if subcommand == "show":
            if len(cmd.args) < 2:
                return "Usage: /escalation show <id>"
            return await self._escalation_show(cmd.args[1])

        elif subcommand == "approve":
            if len(cmd.args) < 2:
                return "Usage: /escalation approve <id>"
            return await self._escalation_decide(cmd.args[1], Decision.APPROVE, user_id)

        elif subcommand == "reject":
            if len(cmd.args) < 2:
                return "Usage: /escalation reject <id>"
            reason = " ".join(cmd.args[2:]) if len(cmd.args) > 2 else "Rejected by owner"
            return await self._escalation_decide(cmd.args[1], Decision.REJECT, user_id, reason)

        elif subcommand == "moreinfo":
            if len(cmd.args) < 2:
                return "Usage: /escalation moreinfo <id>"
            reason = " ".join(cmd.args[2:]) if len(cmd.args) > 2 else "More information needed"
            return await self._escalation_decide(cmd.args[1], Decision.MORE_INFO, user_id, reason)

        else:
            return f"Unknown subcommand: {subcommand}. Use show, approve, reject, or moreinfo."

    async def _escalation_show(self, escalation_id: str) -> str:
        """Show details of a specific escalation."""
        request = self.escalation_manager.get_request(escalation_id)

        if not request:
            return f"Escalation `{escalation_id}` not found."

        return request.to_telegram_summary()

    async def _escalation_decide(
        self,
        escalation_id: str,
        decision: Decision,
        user_id: int,
        rationale: str = ""
    ) -> str:
        """Record a decision on an escalation."""
        # Only Owners can approve/reject
        if not self.is_owner(user_id):
            return "Only Owners can approve/reject escalations."

        request = self.escalation_manager.get_request(escalation_id)
        if not request:
            return f"Escalation `{escalation_id}` not found."

        if request.is_expired:
            return f"Escalation `{escalation_id}` has expired."

        if request.pending_stage == "complete":
            return f"Escalation `{escalation_id}` is already complete."

        if request.pending_stage == "manager":
            return f"Escalation `{escalation_id}` is still pending Manager review."

        # Record owner decision
        result = self.escalation_manager.owner_decide(
            escalation_id=escalation_id,
            decision=decision,
            rationale=rationale or f"{decision.value} by owner",
            decider_telegram_id=user_id,
        )

        if not result:
            return f"Failed to record decision for `{escalation_id}`."

        emoji = {"approve": "✅", "reject": "❌", "more_info": "ℹ️"}
        return f"{emoji.get(decision.value, '❓')} Escalation `{escalation_id}` {decision.value}d."

    async def _handle_stop(self, cmd: ParsedCommand, user_id: int) -> str:
        """Stop all agents. Available to Owners and break-glass admins."""
        if self._stop_callback:
            try:
                self._stop_callback()
                return "🛑 Stop signal sent to all agents."
            except Exception as e:
                return f"Error stopping agents: {safe_log(str(e))}"
        return "No stop callback configured."

    # ═══════════════════════════════════════════════════════════════════════════
    # POLLING / START
    # ═══════════════════════════════════════════════════════════════════════════

    async def start(self):
        """Start the bot polling loop."""
        import httpx

        self._running = True
        offset = 0

        print(f"[Telegram] Bot starting with {len(self.admin_ids)} owner(s)")

        async with httpx.AsyncClient(timeout=60.0) as client:
            while self._running:
                try:
                    # Long poll for updates
                    response = await client.get(
                        f"https://api.telegram.org/bot{self.token}/getUpdates",
                        params={"offset": offset, "timeout": 30},
                    )
                    data = response.json()

                    if data.get("ok") and data.get("result"):
                        for update in data["result"]:
                            offset = update["update_id"] + 1

                            # Extract message
                            message = update.get("message")
                            if not message:
                                continue

                            user_id = message.get("from", {}).get("id")
                            text = message.get("text", "")
                            chat_id = message.get("chat", {}).get("id")

                            if not user_id or not text:
                                continue

                            # Handle the message
                            response_text = await self.handle_message(user_id, text)

                            if response_text:
                                # Send response
                                await client.post(
                                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                                    json={
                                        "chat_id": chat_id,
                                        "text": response_text,
                                        "parse_mode": "Markdown",
                                    },
                                )

                except httpx.TimeoutException:
                    continue  # Normal for long polling
                except Exception as e:
                    print(f"[Telegram] Polling error: {safe_log(str(e))}")
                    await asyncio.sleep(5)

    def stop(self):
        """Stop the polling loop."""
        self._running = False


# ═══════════════════════════════════════════════════════════════════════════════
# FACTORY
# ═══════════════════════════════════════════════════════════════════════════════

def create_hardened_bot(
    token: str | None = None,
    admin_ids: list[int] | None = None,
    escalation_manager: EscalationManager | None = None,
) -> Optional[HardenedTelegramBot]:
    """
    Create a hardened bot instance, or None if not configured.

    Can be configured via arguments or environment variables.
    """
    try:
        bot = HardenedTelegramBot()

        # Override with explicit arguments if provided
        if token:
            bot.token = token
        if admin_ids:
            bot.admin_ids = set(admin_ids)
        if escalation_manager:
            bot.escalation_manager = escalation_manager

        return bot
    except ValueError as e:
        print(f"[Security] Cannot create hardened bot: {e}")
        return None
