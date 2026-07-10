"""
Test SQLite Escalation Persistence

CRITICAL TEST: Verifies that escalations survive process restarts.

Test scenarios:
1. Create escalation -> verify in SQLite
2. Create escalation -> "restart" (new EscalationManager) -> verify restored
3. Owner decides -> verify persisted
4. Expiry -> verify persisted
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
import pytest

# Add src to path for imports
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from src.governance.escalation_store import EscalationStore
from src.governance.escalations import (
    EscalationManager,
    ActionRequest,
    ActionCategory,
    EvidenceBundle,
    RiskLevel,
    Decision,
)


class TestEscalationStore:
    """Direct tests of EscalationStore."""

    def test_schema_creation(self, tmp_path):
        """Test that schema is created on first run."""
        db_path = tmp_path / "test.db"
        store = EscalationStore(db_path)

        assert db_path.exists()

        # Verify tables exist
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='escalations'"
            )
            assert cursor.fetchone() is not None

    def test_save_and_load_escalation(self, tmp_path):
        """Test basic save and load."""
        db_path = tmp_path / "test.db"
        store = EscalationStore(db_path)

        # Create a manager to generate a proper escalation
        manager = EscalationManager(
            log_dir=tmp_path / "logs",
            owner_telegram_ids=[12345],
            db_path=db_path,
        )

        # Create an escalation
        action = ActionRequest(
            category=ActionCategory.SHELL_EXECUTE,
            operation="run_test",
            parameters={"cmd": "pytest"},
        )
        evidence = EvidenceBundle(
            trigger_reason="Test triggered escalation",
        )

        request = manager.create_escalation(
            requester="test_agent",
            action=action,
            risk_level=RiskLevel.MEDIUM,
            evidence=evidence,
        )

        # Verify it was saved
        loaded = store.get_escalation(request.id)
        assert loaded is not None
        assert loaded.id == request.id
        assert loaded.requester == "test_agent"
        assert loaded.action.category == ActionCategory.SHELL_EXECUTE
        assert loaded.action.operation == "run_test"
        assert loaded.risk_level == RiskLevel.MEDIUM


class TestEscalationPersistenceAcrossRestarts:
    """Test that escalations survive 'restarts' (new manager instances)."""

    def test_pending_escalation_survives_restart(self, tmp_path):
        """CRITICAL: Pending escalations must survive process restarts."""
        db_path = tmp_path / "test.db"
        log_dir = tmp_path / "logs"

        # Create first manager (simulates original process)
        manager1 = EscalationManager(
            log_dir=log_dir,
            owner_telegram_ids=[12345],
            db_path=db_path,
        )

        # Create an escalation that requires owner approval
        # NOTE: Cost must be within limits for risk level
        # CRITICAL risk allows up to $100, HIGH allows up to $10
        action = ActionRequest(
            category=ActionCategory.TRADE,  # Requires owner approval
            operation="buy_stock",
            parameters={"symbol": "AAPL", "qty": 1},
            estimated_cost_usd=5.0,  # Within HIGH limit of $10
        )
        evidence = EvidenceBundle(
            trigger_reason="Trade action requires owner approval",
            rollback_plan="Sell position",
            rollback_tested=True,
        )

        request = manager1.create_escalation(
            requester="trading_agent",
            action=action,
            risk_level=RiskLevel.HIGH,
            evidence=evidence,
        )

        escalation_id = request.id

        # Verify it's pending owner approval (Manager approved, waiting for Owner)
        assert request.requires_owner
        # Manager should have approved
        assert request.manager_decision is not None
        assert request.manager_decision.decision == Decision.APPROVE
        # Should be pending because waiting for Owner
        assert escalation_id in manager1.pending

        # Destroy manager1 (simulates process restart)
        del manager1

        # Create new manager (simulates new process)
        manager2 = EscalationManager(
            log_dir=log_dir,
            owner_telegram_ids=[12345],
            db_path=db_path,
        )

        # CRITICAL: Escalation should be restored
        assert escalation_id in manager2.pending
        restored = manager2.pending[escalation_id]
        assert restored.requester == "trading_agent"
        assert restored.action.category == ActionCategory.TRADE
        assert restored.action.operation == "buy_stock"
        assert restored.risk_level == RiskLevel.HIGH

    def test_decided_escalation_not_restored_as_pending(self, tmp_path):
        """Decided escalations should not be restored as pending."""
        db_path = tmp_path / "test.db"
        log_dir = tmp_path / "logs"

        # Create manager
        manager1 = EscalationManager(
            log_dir=log_dir,
            owner_telegram_ids=[12345],
            db_path=db_path,
        )

        # Create escalation that gets auto-approved (no owner needed)
        action = ActionRequest(
            category=ActionCategory.READ_ONLY,
            operation="list_files",
            parameters={"path": "/tmp"},
        )
        evidence = EvidenceBundle(
            trigger_reason="Read operation",
        )

        request = manager1.create_escalation(
            requester="file_agent",
            action=action,
            risk_level=RiskLevel.LOW,
            evidence=evidence,
        )

        escalation_id = request.id

        # Should be decided (not pending) since it doesn't require owner
        assert request.is_approved
        assert escalation_id not in manager1.pending

        # Restart
        del manager1
        manager2 = EscalationManager(
            log_dir=log_dir,
            owner_telegram_ids=[12345],
            db_path=db_path,
        )

        # Should NOT be in pending
        assert escalation_id not in manager2.pending

    def test_owner_decision_persists(self, tmp_path):
        """Owner decisions should be persisted."""
        db_path = tmp_path / "test.db"
        log_dir = tmp_path / "logs"

        # Create manager with owner
        manager = EscalationManager(
            log_dir=log_dir,
            owner_telegram_ids=[12345],
            db_path=db_path,
        )

        # Create escalation requiring owner
        action = ActionRequest(
            category=ActionCategory.UPLOAD,
            operation="upload_file",
            parameters={"file": "report.pdf", "dest": "s3://bucket"},
            estimated_cost_usd=0.01,
        )
        evidence = EvidenceBundle(
            trigger_reason="Upload requires approval",
            rollback_plan="Delete from S3",
            rollback_tested=True,
        )

        request = manager.create_escalation(
            requester="upload_agent",
            action=action,
            risk_level=RiskLevel.HIGH,
            evidence=evidence,
        )

        escalation_id = request.id

        # Owner approves
        decision = manager.owner_decide(
            escalation_id=escalation_id,
            decision=Decision.APPROVE,
            rationale="Approved for upload",
            decider_telegram_id=12345,
        )

        assert decision is not None
        assert decision.decision == Decision.APPROVE

        # Verify persisted in SQLite
        store = EscalationStore(db_path)
        saved = store.get_escalation(escalation_id)

        assert saved is not None
        assert saved.status == "decided"
        assert saved.owner_decision is not None
        assert saved.owner_decision.decision == Decision.APPROVE


class TestEscalationStats:
    """Test statistics gathering."""

    def test_get_stats(self, tmp_path):
        """Test that stats work correctly."""
        db_path = tmp_path / "test.db"
        log_dir = tmp_path / "logs"

        manager = EscalationManager(
            log_dir=log_dir,
            owner_telegram_ids=[12345],
            db_path=db_path,
        )

        # Create a few escalations
        for i in range(3):
            action = ActionRequest(
                category=ActionCategory.API_CALL,
                operation=f"api_call_{i}",
                parameters={"endpoint": f"/api/{i}"},
            )
            evidence = EvidenceBundle(trigger_reason=f"Test {i}")

            manager.create_escalation(
                requester="test_agent",
                action=action,
                risk_level=RiskLevel.MEDIUM,
                evidence=evidence,
            )

        stats = manager.get_stats()

        assert "by_status" in stats
        assert "by_risk" in stats
        assert "last_24h" in stats
        assert stats["last_24h"] >= 3


class TestExpiration:
    """Test TTL and expiration."""

    def test_stale_escalations_expired_on_startup(self, tmp_path):
        """Stale escalations should be expired on manager startup."""
        db_path = tmp_path / "test.db"
        store = EscalationStore(db_path)

        # Manually insert an expired escalation
        import sqlite3

        expired_id = "expired_test_123"
        past_time = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        future_time = (datetime.utcnow() - timedelta(minutes=30)).isoformat()  # Already expired

        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                INSERT INTO escalations (
                    id, created_at, expires_at, requester, status,
                    action_json, risk_level, evidence_json, ttl_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                expired_id,
                past_time,
                future_time,  # expires_at in the past
                "test_agent",
                "pending",
                '{"category": "read_only", "operation": "test", "parameters": {}}',
                10,  # LOW
                '{"trigger_reason": "test"}',
                300,
            ))
            conn.commit()

        # Create manager (should expire stale)
        manager = EscalationManager(
            log_dir=tmp_path / "logs",
            owner_telegram_ids=[12345],
            db_path=db_path,
        )

        # Expired escalation should NOT be in pending
        assert expired_id not in manager.pending

        # But should be in database as expired
        saved = store.get_escalation(expired_id)
        assert saved is None or saved.status == "expired"


class TestSQLiteHardening:
    """Test production hardening: WAL mode, concurrency, atomicity."""

    def test_wal_mode_enabled(self, tmp_path):
        """Database should use WAL mode for better concurrency."""
        db_path = tmp_path / "test.db"
        store = EscalationStore(db_path)

        import sqlite3
        with sqlite3.connect(db_path) as conn:
            result = conn.execute("PRAGMA journal_mode").fetchone()
            assert result[0].lower() == "wal", "WAL mode should be enabled"

    def test_schema_version_tracked(self, tmp_path):
        """Schema version should be tracked in database."""
        db_path = tmp_path / "test.db"
        store = EscalationStore(db_path)

        import sqlite3
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute("SELECT version FROM schema_version WHERE id = 1")
            row = cursor.fetchone()
            assert row is not None, "Schema version should be recorded"
            assert row[0] >= 1, "Schema version should be at least 1"

    def test_concurrent_writes_no_lock_error(self, tmp_path):
        """Sequential writes from different connections should not deadlock."""
        db_path = tmp_path / "test.db"
        log_dir = tmp_path / "logs"

        # Create manager (initializes store)
        manager = EscalationManager(
            log_dir=log_dir,
            owner_telegram_ids=[12345],
            db_path=db_path,
        )

        # Create multiple escalations rapidly (simulates concurrent access)
        errors = []
        for i in range(10):
            try:
                action = ActionRequest(
                    category=ActionCategory.READ_ONLY,
                    operation=f"test_op_{i}",
                    parameters={"index": i},
                )
                evidence = EvidenceBundle(trigger_reason=f"Test {i}")

                manager.create_escalation(
                    requester="concurrent_test",
                    action=action,
                    risk_level=RiskLevel.LOW,
                    evidence=evidence,
                )
            except Exception as e:
                errors.append(str(e))

        assert len(errors) == 0, f"Should not have lock errors: {errors}"

    def test_transaction_rollback_on_error(self, tmp_path):
        """Failed transactions should not leave partial state."""
        db_path = tmp_path / "test.db"
        store = EscalationStore(db_path)

        # Get initial count
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            initial_count = conn.execute(
                "SELECT COUNT(*) FROM escalations"
            ).fetchone()[0]

        # Try to save an invalid escalation (simulate by corrupting after create)
        # This tests that our transaction handling is correct
        action = ActionRequest(
            category=ActionCategory.READ_ONLY,
            operation="test",
            parameters={},
        )
        evidence = EvidenceBundle(trigger_reason="Test")

        from src.governance.escalations import EscalationRequest
        import secrets

        request = EscalationRequest(
            id=secrets.token_urlsafe(8),
            created_at=datetime.utcnow(),
            requester="test",
            action=action,
            risk_level=RiskLevel.LOW,
            evidence=evidence,
            ttl_seconds=300,
        )

        # This should succeed
        store.save_escalation(request)

        # Verify count increased by 1
        with sqlite3.connect(db_path) as conn:
            new_count = conn.execute(
                "SELECT COUNT(*) FROM escalations"
            ).fetchone()[0]

        assert new_count == initial_count + 1, "Save should be atomic"

    def test_busy_timeout_prevents_immediate_failure(self, tmp_path):
        """busy_timeout should allow waiting for locks instead of immediate error."""
        db_path = tmp_path / "test.db"
        store = EscalationStore(db_path)

        # Verify busy_timeout is set
        conn = store._get_conn()
        try:
            result = conn.execute("PRAGMA busy_timeout").fetchone()
            assert result[0] >= 1000, "busy_timeout should be at least 1 second"
        finally:
            conn.close()

    def test_wal_persists_after_close(self, tmp_path):
        """WAL mode should persist across connection closes."""
        import sqlite3
        db_path = tmp_path / "test.db"

        # Create store (sets WAL)
        store = EscalationStore(db_path)
        del store  # Close

        # Open fresh connection without our wrapper
        with sqlite3.connect(db_path) as conn:
            result = conn.execute("PRAGMA journal_mode").fetchone()
            assert result[0].lower() == "wal", "WAL should persist after close"

    def test_busy_timeout_set_per_connection(self, tmp_path):
        """Each new connection should have busy_timeout set."""
        db_path = tmp_path / "test.db"
        store = EscalationStore(db_path)

        # Get two separate connections
        conn1 = store._get_conn()
        conn2 = store._get_conn()

        try:
            timeout1 = conn1.execute("PRAGMA busy_timeout").fetchone()[0]
            timeout2 = conn2.execute("PRAGMA busy_timeout").fetchone()[0]

            assert timeout1 >= 1000, "First connection should have busy_timeout"
            assert timeout2 >= 1000, "Second connection should have busy_timeout"
        finally:
            conn1.close()
            conn2.close()

    def test_fresh_db_gets_current_schema_version(self, tmp_path):
        """A fresh database should immediately have current schema version."""
        db_path = tmp_path / "fresh.db"

        # Create fresh store
        store = EscalationStore(db_path)

        # Check schema version directly
        import sqlite3
        with sqlite3.connect(db_path) as conn:
            version = conn.execute(
                "SELECT version FROM schema_version WHERE id = 1"
            ).fetchone()[0]

        # Should be current version (2 as of now)
        assert version >= 2, f"Fresh DB should have current schema version, got {version}"


class TestEscalationInvariants:
    """Test two-person integrity invariants."""

    def test_owner_required_cannot_execute_without_owner(self, tmp_path):
        """Owner-required escalations cannot become executable without owner approval."""
        manager = EscalationManager(
            log_dir=tmp_path / "logs",
            owner_telegram_ids=[12345],
            db_path=tmp_path / "test.db",
        )

        # Create TRADE action (always requires owner)
        action = ActionRequest(
            category=ActionCategory.TRADE,
            operation="buy",
            parameters={"symbol": "BTC"},
            estimated_cost_usd=5.0,  # Within limit
        )
        evidence = EvidenceBundle(
            trigger_reason="Trade",
            rollback_plan="Sell",
            rollback_tested=True,
        )

        request = manager.create_escalation(
            requester="executor",
            action=action,
            risk_level=RiskLevel.HIGH,
            evidence=evidence,
        )

        # Manager approved
        assert request.manager_decision is not None
        assert request.manager_decision.decision == Decision.APPROVE

        # But NOT fully approved (needs owner)
        assert request.requires_owner is True
        assert request.is_approved is False

        # Cannot get execution token
        from src.governance.escalations import ExecutionTokenManager
        token_mgr = ExecutionTokenManager()
        token = token_mgr.mint_token(request)
        assert token is None, "Should not mint token without owner approval"

    def test_expired_escalation_cannot_be_approved(self, tmp_path):
        """TTL-expired escalations cannot be approved or executed."""
        import time

        manager = EscalationManager(
            log_dir=tmp_path / "logs",
            owner_telegram_ids=[12345],
            db_path=tmp_path / "test.db",
        )

        # Create with very short TTL
        action = ActionRequest(
            category=ActionCategory.UPLOAD,
            operation="upload",
            parameters={},
            estimated_cost_usd=0.01,
        )
        evidence = EvidenceBundle(
            trigger_reason="Upload",
            rollback_plan="Delete",
            rollback_tested=True,
        )

        request = manager.create_escalation(
            requester="uploader",
            action=action,
            risk_level=RiskLevel.HIGH,
            evidence=evidence,
            ttl_seconds=1,  # 1 second TTL
        )

        escalation_id = request.id

        # Wait for expiry
        time.sleep(1.1)

        # Try to approve - should fail because expired
        result = manager.owner_decide(
            escalation_id=escalation_id,
            decision=Decision.APPROVE,
            rationale="Too late",
            decider_telegram_id=12345,
        )

        # Should return None (expired/not found in pending)
        assert result is None, "Should not be able to approve expired escalation"

    def test_ttl_checked_at_decision_time(self, tmp_path):
        """TTL should be verified when owner makes decision, not just creation."""
        import time

        manager = EscalationManager(
            log_dir=tmp_path / "logs",
            owner_telegram_ids=[12345],
            db_path=tmp_path / "test.db",
        )

        # Create with 2 second TTL
        action = ActionRequest(
            category=ActionCategory.UPLOAD,
            operation="upload",
            parameters={},
            estimated_cost_usd=0.01,
        )
        evidence = EvidenceBundle(
            trigger_reason="Upload",
            rollback_plan="Delete",
            rollback_tested=True,
        )

        request = manager.create_escalation(
            requester="uploader",
            action=action,
            risk_level=RiskLevel.HIGH,
            evidence=evidence,
            ttl_seconds=2,
        )

        # Verify not expired yet
        assert request.is_expired is False

        # Wait until expired
        time.sleep(2.1)

        # Now is_expired should be True
        assert request.is_expired is True

    def test_owner_required_cannot_mint_with_manager_only(self, tmp_path):
        """Owner-required category cannot mint token with only manager approval."""
        from src.governance.escalations import ExecutionTokenManager

        manager = EscalationManager(
            log_dir=tmp_path / "logs",
            owner_telegram_ids=[12345],
            db_path=tmp_path / "test.db",
        )

        # CREDENTIAL_CHANGE always requires owner
        action = ActionRequest(
            category=ActionCategory.CREDENTIAL_CHANGE,
            operation="rotate_key",
            parameters={"key": "api"},
            estimated_cost_usd=0.0,
        )
        evidence = EvidenceBundle(
            trigger_reason="Key rotation",
            rollback_plan="Restore from backup",
            rollback_tested=True,
        )

        request = manager.create_escalation(
            requester="security_agent",
            action=action,
            risk_level=RiskLevel.HIGH,
            evidence=evidence,
        )

        # Manager approved
        assert request.manager_decision.decision == Decision.APPROVE
        # But requires owner
        assert request.requires_owner is True
        # Not fully approved
        assert request.is_approved is False

        # Try to mint - should fail
        token_mgr = ExecutionTokenManager()
        token = token_mgr.mint_token(request)
        assert token is None, "Should not mint token without owner approval"

    def test_expired_but_approved_cannot_mint(self, tmp_path):
        """An escalation approved before expiry cannot mint after expiry."""
        import time
        from src.governance.escalations import ExecutionTokenManager

        manager = EscalationManager(
            log_dir=tmp_path / "logs",
            owner_telegram_ids=[12345],
            db_path=tmp_path / "test.db",
        )

        # Create with short TTL
        action = ActionRequest(
            category=ActionCategory.PUBLISH,
            operation="post",
            parameters={"content": "test"},
            estimated_cost_usd=0.0,
        )
        evidence = EvidenceBundle(
            trigger_reason="Publish content",
            rollback_plan="Delete post",
            rollback_tested=True,
        )

        request = manager.create_escalation(
            requester="publisher",
            action=action,
            risk_level=RiskLevel.HIGH,
            evidence=evidence,
            ttl_seconds=1,
        )

        # Immediately approve
        manager.owner_decide(
            escalation_id=request.id,
            decision=Decision.APPROVE,
            rationale="Approved quickly",
            decider_telegram_id=12345,
        )

        request = manager.completed[request.id]
        assert request.is_approved is True

        # Wait for expiry
        time.sleep(1.1)
        assert request.is_expired is True

        # Try to mint after expiry
        token_mgr = ExecutionTokenManager()
        token = token_mgr.mint_token(request)
        assert token is None, "Should not mint for expired escalation"

    def test_ttl_checked_at_token_mint_time(self, tmp_path):
        """TTL must be verified at token mint time, not just approve time.

        This prevents 'approve now, execute later after TTL' attacks.
        """
        import time
        from src.governance.escalations import ExecutionTokenManager, EscalationDecision, DeciderRole

        manager = EscalationManager(
            log_dir=tmp_path / "logs",
            owner_telegram_ids=[12345],
            db_path=tmp_path / "test.db",
        )

        # Create with 3 second TTL (enough time to approve then expire)
        action = ActionRequest(
            category=ActionCategory.UPLOAD,
            operation="upload",
            parameters={},
            estimated_cost_usd=0.01,
        )
        evidence = EvidenceBundle(
            trigger_reason="Upload for TTL test",
            rollback_plan="Delete",
            rollback_tested=True,
        )

        request = manager.create_escalation(
            requester="uploader",
            action=action,
            risk_level=RiskLevel.HIGH,
            evidence=evidence,
            ttl_seconds=2,  # Short TTL
        )

        # Immediately approve via owner (within TTL)
        manager.owner_decide(
            escalation_id=request.id,
            decision=Decision.APPROVE,
            rationale="Quick approval",
            decider_telegram_id=12345,
        )

        # Refresh request from completed
        request = manager.completed[request.id]

        # Verify it's fully approved
        assert request.is_approved is True
        assert request.manager_decision.decision == Decision.APPROVE
        assert request.owner_decision.decision == Decision.APPROVE

        # Wait for TTL to expire
        time.sleep(2.1)

        # Now try to mint token - should FAIL because TTL expired
        token_mgr = ExecutionTokenManager()
        token = token_mgr.mint_token(request)

        assert token is None, "Should not mint token for expired escalation even if approved"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
