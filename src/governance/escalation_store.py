"""
SQLite Persistence for Escalation System

CRITICAL: Without this, process restarts lose all pending approvals.

This module provides:
- save_escalation() - Persist escalation to SQLite
- load_pending() - Load all pending escalations on startup
- mark_resolved() - Mark escalation as completed/expired
- Automatic schema creation on first run

HARDENING (v2):
- WAL mode for better concurrency (multiple readers, single writer)
- busy_timeout to handle lock contention gracefully
- Schema versioning for safe migrations
- Atomic transactions with BEGIN IMMEDIATE
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .escalations import (
    EscalationRequest,
    EscalationDecision,
    ActionRequest,
    ActionCategory,
    EvidenceBundle,
    RiskLevel,
    DeciderRole,
    Decision,
)


class EscalationStore:
    """
    SQLite-backed persistence for escalations.

    Survives process restarts, crashes, and deployments.

    PRODUCTION HARDENING:
    - WAL mode: Enables concurrent reads during writes
    - busy_timeout: 5 seconds wait on lock (avoids "database is locked")
    - Schema versioning: Safe migrations without manual intervention
    - Atomic UPSERT: No partial writes
    """

    # Current schema version - increment when schema changes
    SCHEMA_VERSION = 2

    SCHEMA_V1 = """
    CREATE TABLE IF NOT EXISTS escalations (
        id TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        requester TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',

        -- Action details (JSON)
        action_json TEXT NOT NULL,
        risk_level INTEGER NOT NULL,

        -- Evidence (JSON)
        evidence_json TEXT NOT NULL,

        -- TTL
        ttl_seconds INTEGER NOT NULL,

        -- Decisions (JSON, nullable)
        manager_decision_json TEXT,
        owner_decision_json TEXT,

        -- Timestamps
        resolved_at TEXT,

        -- Indexes
        created_at_idx TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_escalations_status ON escalations(status);
    CREATE INDEX IF NOT EXISTS idx_escalations_created ON escalations(created_at);
    CREATE INDEX IF NOT EXISTS idx_escalations_expires ON escalations(expires_at);
    """

    SCHEMA_VERSION_TABLE = """
    CREATE TABLE IF NOT EXISTS schema_version (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        version INTEGER NOT NULL,
        migrated_at TEXT NOT NULL
    );
    """

    # Connection settings for production stability
    BUSY_TIMEOUT_MS = 5000  # 5 seconds
    WAL_MODE = "wal"
    SYNCHRONOUS_MODE = "NORMAL"  # Good balance of durability/performance with WAL

    def __init__(self, db_path: Path = Path("data/escalations.db")):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()

    def _init_database(self):
        """Initialize database with production settings and migrations."""
        conn = self._get_conn()
        try:
            # Enable WAL mode (persistent, survives reconnects)
            result = conn.execute("PRAGMA journal_mode=WAL").fetchone()
            if result[0].lower() != self.WAL_MODE:
                print(f"[EscalationStore] Warning: WAL mode not enabled, got {result[0]}")

            # Set synchronous mode
            conn.execute(f"PRAGMA synchronous={self.SYNCHRONOUS_MODE}")

            # Create version table if needed
            conn.executescript(self.SCHEMA_VERSION_TABLE)

            # Check current version
            current_version = self._get_schema_version(conn)

            if current_version == 0:
                # Fresh database - apply full schema
                conn.executescript(self.SCHEMA_V1)
                self._set_schema_version(conn, 1)
                current_version = 1

            # Apply migrations as needed
            if current_version < self.SCHEMA_VERSION:
                self._run_migrations(conn, current_version, self.SCHEMA_VERSION)

            conn.commit()
        finally:
            conn.close()

    def _get_schema_version(self, conn: sqlite3.Connection) -> int:
        """Get current schema version (0 if no version table populated)."""
        try:
            cursor = conn.execute("SELECT version FROM schema_version WHERE id = 1")
            row = cursor.fetchone()
            return row[0] if row else 0
        except sqlite3.OperationalError:
            return 0

    def _set_schema_version(self, conn: sqlite3.Connection, version: int):
        """Set schema version."""
        conn.execute("""
            INSERT OR REPLACE INTO schema_version (id, version, migrated_at)
            VALUES (1, ?, ?)
        """, (version, datetime.utcnow().isoformat()))

    def _run_migrations(self, conn: sqlite3.Connection, from_version: int, to_version: int):
        """Run schema migrations incrementally."""
        print(f"[EscalationStore] Migrating schema from v{from_version} to v{to_version}")

        for v in range(from_version + 1, to_version + 1):
            migration_method = getattr(self, f"_migrate_v{v}", None)
            if migration_method:
                print(f"[EscalationStore] Applying migration v{v}")
                migration_method(conn)
            self._set_schema_version(conn, v)

        print(f"[EscalationStore] Migration complete, now at v{to_version}")

    def _migrate_v2(self, conn: sqlite3.Connection):
        """Migration v2: Add index on requester for faster agent-specific queries."""
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_escalations_requester
            ON escalations(requester)
        """)

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection with production settings."""
        conn = sqlite3.connect(
            self.db_path,
            timeout=self.BUSY_TIMEOUT_MS / 1000,  # Convert to seconds
            isolation_level=None,  # We'll manage transactions explicitly
        )
        conn.row_factory = sqlite3.Row

        # Set busy timeout (milliseconds)
        conn.execute(f"PRAGMA busy_timeout={self.BUSY_TIMEOUT_MS}")

        return conn

    # ═══════════════════════════════════════════════════════════════════════════
    # SERIALIZATION HELPERS
    # ═══════════════════════════════════════════════════════════════════════════

    def _action_to_json(self, action: ActionRequest) -> str:
        """Serialize ActionRequest to JSON."""
        return json.dumps({
            "category": action.category.value,
            "operation": action.operation,
            "parameters": action.parameters,
            "reversible": action.reversible,
            "rollback_command": action.rollback_command,
            "estimated_cost_usd": action.estimated_cost_usd,
            "affected_resources": action.affected_resources,
        })

    def _action_from_json(self, json_str: str) -> ActionRequest:
        """Deserialize ActionRequest from JSON."""
        data = json.loads(json_str)
        return ActionRequest(
            category=ActionCategory(data["category"]),
            operation=data["operation"],
            parameters=data["parameters"],
            reversible=data.get("reversible", True),
            rollback_command=data.get("rollback_command"),
            estimated_cost_usd=data.get("estimated_cost_usd", 0.0),
            affected_resources=data.get("affected_resources", []),
        )

    def _evidence_to_json(self, evidence: EvidenceBundle) -> str:
        """Serialize EvidenceBundle to JSON."""
        return json.dumps({
            "trigger_reason": evidence.trigger_reason,
            "bylaw_matched": evidence.bylaw_matched,
            "input_summary": evidence.input_summary,
            "simulation_result": evidence.simulation_result,
            "diff_preview": evidence.diff_preview,
            "log_refs": evidence.log_refs,
            "screenshot_refs": evidence.screenshot_refs,
            "rollback_plan": evidence.rollback_plan,
            "rollback_tested": evidence.rollback_tested,
        })

    def _evidence_from_json(self, json_str: str) -> EvidenceBundle:
        """Deserialize EvidenceBundle from JSON."""
        data = json.loads(json_str)
        return EvidenceBundle(
            trigger_reason=data["trigger_reason"],
            bylaw_matched=data.get("bylaw_matched"),
            input_summary=data.get("input_summary", ""),
            simulation_result=data.get("simulation_result"),
            diff_preview=data.get("diff_preview"),
            log_refs=data.get("log_refs", []),
            screenshot_refs=data.get("screenshot_refs", []),
            rollback_plan=data.get("rollback_plan"),
            rollback_tested=data.get("rollback_tested", False),
        )

    def _decision_to_json(self, decision: EscalationDecision | None) -> str | None:
        """Serialize EscalationDecision to JSON."""
        if decision is None:
            return None
        return json.dumps({
            "id": decision.id,
            "decided_at": decision.decided_at.isoformat(),
            "decider_role": decision.decider_role.value,
            "decider_id": decision.decider_id,
            "decision": decision.decision.value,
            "rationale": decision.rationale,
            "conditions": decision.conditions,
        })

    def _decision_from_json(self, json_str: str | None) -> EscalationDecision | None:
        """Deserialize EscalationDecision from JSON."""
        if json_str is None:
            return None
        data = json.loads(json_str)
        return EscalationDecision(
            id=data["id"],
            decided_at=datetime.fromisoformat(data["decided_at"]),
            decider_role=DeciderRole(data["decider_role"]),
            decider_id=data["decider_id"],
            decision=Decision(data["decision"]),
            rationale=data["rationale"],
            conditions=data.get("conditions", []),
        )

    # ═══════════════════════════════════════════════════════════════════════════
    # CORE OPERATIONS
    # ═══════════════════════════════════════════════════════════════════════════

    def save_escalation(self, request: EscalationRequest):
        """
        Persist an escalation request to SQLite.

        Called after create_escalation() and after any state change.

        Uses BEGIN IMMEDIATE for single-writer enforcement and atomicity.
        """
        conn = self._get_conn()
        try:
            # BEGIN IMMEDIATE acquires write lock immediately, avoiding deadlocks
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                INSERT OR REPLACE INTO escalations (
                    id, created_at, expires_at, requester, status,
                    action_json, risk_level, evidence_json, ttl_seconds,
                    manager_decision_json, owner_decision_json, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                request.id,
                request.created_at.isoformat(),
                request.expires_at.isoformat(),
                request.requester,
                request.status,
                self._action_to_json(request.action),
                request.risk_level.value,
                self._evidence_to_json(request.evidence),
                request.ttl_seconds,
                self._decision_to_json(request.manager_decision),
                self._decision_to_json(request.owner_decision),
                datetime.utcnow().isoformat() if request.status != "pending" else None,
            ))
            conn.execute("COMMIT")
        except Exception as e:
            conn.execute("ROLLBACK")
            raise e
        finally:
            conn.close()

    def load_pending(self) -> list[EscalationRequest]:
        """
        Load all pending escalations from SQLite.

        Called during EscalationManager initialization to restore state.
        Returns only non-expired pending requests.
        """
        now = datetime.utcnow()
        results = []

        with self._get_conn() as conn:
            cursor = conn.execute("""
                SELECT * FROM escalations
                WHERE status = 'pending'
                AND expires_at > ?
                ORDER BY created_at ASC
            """, (now.isoformat(),))

            for row in cursor:
                request = self._row_to_request(row)
                if request:
                    results.append(request)

        return results

    def load_all(self, limit: int = 100) -> list[EscalationRequest]:
        """Load all escalations (for history/audit)."""
        results = []

        with self._get_conn() as conn:
            cursor = conn.execute("""
                SELECT * FROM escalations
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))

            for row in cursor:
                request = self._row_to_request(row)
                if request:
                    results.append(request)

        return results

    def get_escalation(self, escalation_id: str) -> EscalationRequest | None:
        """Get a specific escalation by ID."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT * FROM escalations WHERE id = ?",
                (escalation_id,)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_request(row)
        return None

    def mark_resolved(self, escalation_id: str, status: str = "decided"):
        """Mark an escalation as resolved (decided/expired/cancelled)."""
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                UPDATE escalations
                SET status = ?, resolved_at = ?
                WHERE id = ?
            """, (status, datetime.utcnow().isoformat(), escalation_id))
            conn.execute("COMMIT")
        except Exception as e:
            conn.execute("ROLLBACK")
            raise e
        finally:
            conn.close()

    def expire_stale(self) -> int:
        """Expire all escalations past their TTL. Returns count expired."""
        now = datetime.utcnow()
        conn = self._get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute("""
                UPDATE escalations
                SET status = 'expired', resolved_at = ?
                WHERE status = 'pending' AND expires_at <= ?
            """, (now.isoformat(), now.isoformat()))
            count = cursor.rowcount
            conn.execute("COMMIT")
            return count
        except Exception as e:
            conn.execute("ROLLBACK")
            raise e
        finally:
            conn.close()

    def _row_to_request(self, row: sqlite3.Row) -> EscalationRequest | None:
        """Convert a database row to an EscalationRequest."""
        try:
            return EscalationRequest(
                id=row["id"],
                created_at=datetime.fromisoformat(row["created_at"]),
                requester=row["requester"],
                action=self._action_from_json(row["action_json"]),
                risk_level=RiskLevel(row["risk_level"]),
                evidence=self._evidence_from_json(row["evidence_json"]),
                ttl_seconds=row["ttl_seconds"],
                status=row["status"],
                manager_decision=self._decision_from_json(row["manager_decision_json"]),
                owner_decision=self._decision_from_json(row["owner_decision_json"]),
            )
        except Exception as e:
            print(f"[EscalationStore] Failed to deserialize row {row['id']}: {e}")
            return None

    # ═══════════════════════════════════════════════════════════════════════════
    # STATISTICS
    # ═══════════════════════════════════════════════════════════════════════════

    def get_stats(self) -> dict[str, Any]:
        """Get escalation statistics."""
        with self._get_conn() as conn:
            stats = {}

            # Count by status
            cursor = conn.execute("""
                SELECT status, COUNT(*) as count
                FROM escalations
                GROUP BY status
            """)
            stats["by_status"] = {row["status"]: row["count"] for row in cursor}

            # Count by risk level
            cursor = conn.execute("""
                SELECT risk_level, COUNT(*) as count
                FROM escalations
                GROUP BY risk_level
            """)
            stats["by_risk"] = {
                RiskLevel(row["risk_level"]).name: row["count"]
                for row in cursor
            }

            # Recent activity (last 24h)
            yesterday = datetime.utcnow().isoformat()[:10]
            cursor = conn.execute("""
                SELECT COUNT(*) as count
                FROM escalations
                WHERE created_at >= ?
            """, (yesterday,))
            stats["last_24h"] = cursor.fetchone()["count"]

            return stats


# ═══════════════════════════════════════════════════════════════════════════════
# EXPORTS
# ═══════════════════════════════════════════════════════════════════════════════

__all__ = ["EscalationStore"]
