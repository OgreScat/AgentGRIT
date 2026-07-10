"""
AgentGRIT Trust Management System

Manages trust levels for task types and file paths.
Trust is earned through successful completions and lost through failures.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

try:
    from ..config import settings
    _PROMOTE_DEFAULT = settings.trust_promote_threshold
    _AUTONOMOUS_DEFAULT = settings.trust_autonomous_threshold
except Exception:
    # Config pulls heavy deps (pydantic-settings). The trust ladder must be
    # runnable standalone (e.g. from the eval runner), so fall back to the
    # documented defaults if config can't load.
    _PROMOTE_DEFAULT = 5
    _AUTONOMOUS_DEFAULT = 20


class TrustLevel(Enum):
    """Trust levels for agent operations."""
    
    UNTRUSTED = "untrusted"    # New task types, unfamiliar territory
    TRUSTED = "trusted"        # Proven patterns, 5+ successes
    AUTONOMOUS = "autonomous"  # Battle-tested, 20+ consecutive successes


@dataclass
class TrustPermissions:
    """Permissions granted at each trust level."""
    
    max_files_per_commit: int | None  # None = unlimited
    auto_commit: bool
    auto_push: bool
    require_all_tests_pass: bool
    require_lint_pass: bool
    require_human_review: bool
    can_fix_lint_itself: bool


# Permission configurations for each trust level
TRUST_PERMISSIONS: dict[TrustLevel, TrustPermissions] = {
    TrustLevel.UNTRUSTED: TrustPermissions(
        max_files_per_commit=3,
        auto_commit=False,
        auto_push=False,
        require_all_tests_pass=True,
        require_lint_pass=True,
        require_human_review=True,
        can_fix_lint_itself=False,
    ),
    TrustLevel.TRUSTED: TrustPermissions(
        max_files_per_commit=10,
        auto_commit=True,
        auto_push=False,
        require_all_tests_pass=True,
        require_lint_pass=True,
        require_human_review=False,
        can_fix_lint_itself=True,
    ),
    TrustLevel.AUTONOMOUS: TrustPermissions(
        max_files_per_commit=None,  # Unlimited
        auto_commit=True,
        auto_push=True,  # Can push to feature branches
        require_all_tests_pass=True,
        require_lint_pass=False,  # Can fix lint itself
        require_human_review=False,
        can_fix_lint_itself=True,
    ),
}


@dataclass
class TrustHistory:
    """Trust history for a task pattern."""
    
    pattern: str
    trust_level: TrustLevel = TrustLevel.UNTRUSTED
    consecutive_successes: int = 0
    consecutive_failures: int = 0
    total_successes: int = 0
    total_failures: int = 0
    last_success: datetime | None = None
    last_failure: datetime | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    # Promotion/demotion tracking
    promoted_at: datetime | None = None
    demoted_at: datetime | None = None
    promotion_reason: str | None = None
    demotion_reason: str | None = None


@dataclass
class TrustEvent:
    """Event recorded in trust history."""
    
    pattern: str
    event_type: str  # "success", "failure", "promotion", "demotion"
    old_level: TrustLevel | None
    new_level: TrustLevel | None
    reason: str
    context: dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)


class TrustManager:
    """
    Manages trust levels for task types and file paths.
    
    Trust is earned through successful completions and lost through failures.
    The system automatically promotes and demotes based on track record.
    """
    
    def __init__(self, state_path: str = "data/trust_state.json"):
        # In-memory cache, backed by a JSON file so trust accumulates across runs.
        self._history: dict[str, TrustHistory] = {}
        self._events: list[TrustEvent] = []
        self._state_path = state_path

        # Thresholds from settings
        self.promote_threshold = _PROMOTE_DEFAULT
        self.autonomous_threshold = _AUTONOMOUS_DEFAULT

        self._load()

    def _load(self) -> None:
        """Load persisted trust state if present (stdlib only)."""
        import json
        from pathlib import Path
        p = Path(self._state_path)
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text())
        except Exception:
            return
        for pat, h in data.get("history", {}).items():
            self._history[pat] = TrustHistory(
                pattern=pat,
                trust_level=TrustLevel(h.get("trust_level", "untrusted")),
                consecutive_successes=h.get("consecutive_successes", 0),
                consecutive_failures=h.get("consecutive_failures", 0),
                total_successes=h.get("total_successes", 0),
                total_failures=h.get("total_failures", 0),
            )

    def _save(self) -> None:
        """Persist trust state (stdlib only). Best-effort; never raises."""
        import json
        from pathlib import Path
        try:
            p = Path(self._state_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "history": {
                    pat: {
                        "trust_level": h.trust_level.value,
                        "consecutive_successes": h.consecutive_successes,
                        "consecutive_failures": h.consecutive_failures,
                        "total_successes": h.total_successes,
                        "total_failures": h.total_failures,
                    }
                    for pat, h in self._history.items()
                }
            }
            p.write_text(json.dumps(data, indent=2))
        except Exception:
            pass
    
    def get_trust_level(self, pattern: str) -> TrustLevel:
        """Get current trust level for a pattern."""
        history = self._history.get(pattern)
        if history is None:
            return TrustLevel.UNTRUSTED
        return history.trust_level
    
    def get_permissions(self, pattern: str) -> TrustPermissions:
        """Get permissions for a pattern based on its trust level."""
        level = self.get_trust_level(pattern)
        return TRUST_PERMISSIONS[level]
    
    async def record_success(
        self,
        pattern: str,
        context: dict[str, Any] | None = None,
    ) -> TrustEvent | None:
        """
        Record a successful task completion.
        
        Returns a TrustEvent if trust level changed, None otherwise.
        """
        context = context or {}
        history = self._get_or_create_history(pattern)
        
        # Update counters
        history.consecutive_successes += 1
        history.consecutive_failures = 0
        history.total_successes += 1
        history.last_success = datetime.utcnow()
        history.updated_at = datetime.utcnow()
        
        # Check for promotion
        event = self._check_promotion(history, context)
        self._save()
        
        return event
    
    async def record_failure(
        self,
        pattern: str,
        reason: str,
        context: dict[str, Any] | None = None,
    ) -> TrustEvent | None:
        """
        Record a task failure.
        
        Returns a TrustEvent if trust level changed, None otherwise.
        """
        context = context or {}
        context["failure_reason"] = reason
        history = self._get_or_create_history(pattern)
        
        # Update counters
        history.consecutive_failures += 1
        history.consecutive_successes = 0
        history.total_failures += 1
        history.last_failure = datetime.utcnow()
        history.updated_at = datetime.utcnow()
        
        # Check for demotion
        event = self._check_demotion(history, reason, context)
        self._save()
        
        return event
    
    def _get_or_create_history(self, pattern: str) -> TrustHistory:
        """Get or create trust history for a pattern."""
        if pattern not in self._history:
            self._history[pattern] = TrustHistory(pattern=pattern)
        return self._history[pattern]
    
    def _check_promotion(
        self,
        history: TrustHistory,
        context: dict[str, Any],
    ) -> TrustEvent | None:
        """Check if pattern should be promoted to higher trust level."""
        old_level = history.trust_level
        new_level = old_level
        reason = ""
        
        if old_level == TrustLevel.UNTRUSTED:
            if history.consecutive_successes >= self.promote_threshold:
                new_level = TrustLevel.TRUSTED
                reason = f"Promoted after {history.consecutive_successes} consecutive successes"
        
        elif old_level == TrustLevel.TRUSTED:
            if (
                history.consecutive_successes >= self.autonomous_threshold
                and history.total_successes >= 50
            ):
                new_level = TrustLevel.AUTONOMOUS
                reason = f"Promoted to autonomous after {history.total_successes} total successes"
        
        if new_level != old_level:
            history.trust_level = new_level
            history.promoted_at = datetime.utcnow()
            history.promotion_reason = reason
            
            event = TrustEvent(
                pattern=history.pattern,
                event_type="promotion",
                old_level=old_level,
                new_level=new_level,
                reason=reason,
                context=context,
            )
            self._events.append(event)
            return event
        
        return None
    
    def _check_demotion(
        self,
        history: TrustHistory,
        reason: str,
        context: dict[str, Any],
    ) -> TrustEvent | None:
        """Check if pattern should be demoted to lower trust level."""
        old_level = history.trust_level
        new_level = old_level
        demotion_reason = ""
        
        # Severe failures demote to untrusted
        severe_keywords = ["security", "production", "data loss", "rollback"]
        is_severe = any(kw in reason.lower() for kw in severe_keywords)
        
        if is_severe:
            new_level = TrustLevel.UNTRUSTED
            demotion_reason = f"Demoted due to severe failure: {reason}"
        
        elif old_level == TrustLevel.AUTONOMOUS:
            # Any failure demotes autonomous
            new_level = TrustLevel.TRUSTED
            demotion_reason = f"Demoted from autonomous after failure: {reason}"
        
        elif old_level == TrustLevel.TRUSTED:
            # 2 consecutive failures demote trusted
            if history.consecutive_failures >= 2:
                new_level = TrustLevel.UNTRUSTED
                demotion_reason = f"Demoted after {history.consecutive_failures} consecutive failures"
        
        if new_level != old_level:
            history.trust_level = new_level
            history.consecutive_successes = 0
            history.demoted_at = datetime.utcnow()
            history.demotion_reason = demotion_reason
            
            event = TrustEvent(
                pattern=history.pattern,
                event_type="demotion",
                old_level=old_level,
                new_level=new_level,
                reason=demotion_reason,
                context=context,
            )
            self._events.append(event)
            return event
        
        return None
    
    def get_history(self, pattern: str) -> TrustHistory | None:
        """Get trust history for a pattern."""
        return self._history.get(pattern)
    
    def get_all_histories(self) -> list[TrustHistory]:
        """Get all trust histories."""
        return list(self._history.values())
    
    def get_recent_events(self, limit: int = 50) -> list[TrustEvent]:
        """Get recent trust events."""
        return sorted(
            self._events,
            key=lambda e: e.timestamp,
            reverse=True,
        )[:limit]
    
    def get_statistics(self) -> dict[str, Any]:
        """Get trust statistics."""
        histories = self.get_all_histories()
        
        by_level = {level: 0 for level in TrustLevel}
        for h in histories:
            by_level[h.trust_level] += 1
        
        total_successes = sum(h.total_successes for h in histories)
        total_failures = sum(h.total_failures for h in histories)
        
        return {
            "total_patterns": len(histories),
            "by_level": {level.value: count for level, count in by_level.items()},
            "total_successes": total_successes,
            "total_failures": total_failures,
            "success_rate": (
                total_successes / (total_successes + total_failures)
                if (total_successes + total_failures) > 0
                else 0
            ),
            "recent_promotions": len([
                e for e in self._events
                if e.event_type == "promotion"
                and e.timestamp > datetime.utcnow() - timedelta(days=7)
            ]),
            "recent_demotions": len([
                e for e in self._events
                if e.event_type == "demotion"
                and e.timestamp > datetime.utcnow() - timedelta(days=7)
            ]),
        }
    
    def suggest_bylaw_updates(self) -> list[str]:
        """
        Analyze patterns and suggest bylaw updates.
        
        This is the self-improvement aspect - learning from outcomes.
        """
        suggestions = []
        
        # Patterns with high success rates could be trusted more
        for history in self._history.values():
            if (
                history.trust_level == TrustLevel.UNTRUSTED
                and history.total_successes >= 10
                and history.total_failures == 0
            ):
                suggestions.append(
                    f"Consider auto-promoting pattern '{history.pattern}' - "
                    f"10+ successes with no failures"
                )
        
        # Patterns with repeated failures might need investigation
        for history in self._history.values():
            if history.consecutive_failures >= 3:
                suggestions.append(
                    f"Investigate pattern '{history.pattern}' - "
                    f"{history.consecutive_failures} consecutive failures"
                )
        
        return suggestions


# Global instance
_manager: TrustManager | None = None


def get_trust_manager() -> TrustManager:
    """Get or create the global trust manager."""
    global _manager
    if _manager is None:
        _manager = TrustManager()
    return _manager
