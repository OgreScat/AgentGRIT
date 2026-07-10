"""
AgentGRIT Database Models

Persistent storage for:
- Tasks and their status
- Agent memory (long-term)
- Trust history
- Content filter cache
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Any

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey,
    Integer, JSON, String, Text, create_engine
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════════

class TaskStatus(PyEnum):
    """Task lifecycle states."""
    QUEUED = "queued"
    RUNNING = "running"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    ESCALATED = "escalated"


class TrustLevel(PyEnum):
    """Agent trust levels."""
    UNTRUSTED = "untrusted"
    TRUSTED = "trusted"
    AUTONOMOUS = "autonomous"


class LLMProvider(PyEnum):
    """LLM providers for routing."""
    OLLAMA = "ollama"
    PERPLEXITY = "perplexity"
    GROK = "grok"
    CLAUDE = "claude"


# ═══════════════════════════════════════════════════════════════════════════════
# TASK MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class Task(Base):
    """A task assigned to an agent."""
    
    __tablename__ = "tasks"
    
    id = Column(String(32), primary_key=True)  # GRIT-YYYYMMDDHHMMSS format
    description = Column(Text, nullable=False)
    status = Column(Enum(TaskStatus), default=TaskStatus.QUEUED)
    priority = Column(String(16), default="normal")  # low, normal, high
    project = Column(String(128), default="default")
    
    # LLM routing
    routed_to = Column(Enum(LLMProvider), nullable=True)
    tokens_used = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    
    # Bylaw decisions
    bylaw_decision = Column(String(32), nullable=True)  # proceed, verify, escalate, block
    bylaw_reason = Column(Text, nullable=True)
    
    # Results
    result = Column(Text, nullable=True)
    files_created = Column(JSON, default=list)
    files_modified = Column(JSON, default=list)
    
    # Verification
    tests_passed = Column(Boolean, nullable=True)
    lint_clean = Column(Boolean, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    parent_task_id = Column(String(32), ForeignKey("tasks.id"), nullable=True)
    subtasks = relationship("Task", backref="parent_task", remote_side=[id])
    
    def __repr__(self):
        return f"<Task {self.id}: {self.status.value}>"
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority,
            "project": self.project,
            "routed_to": self.routed_to.value if self.routed_to else None,
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
            "result": self.result,
            "files_created": self.files_created,
            "files_modified": self.files_modified,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# MEMORY MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class Memory(Base):
    """Long-term agent memory storage."""
    
    __tablename__ = "memories"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_name = Column(String(64), default="GRIT")
    memory_type = Column(String(32))  # fact, preference, tool, pattern
    
    key = Column(String(256), nullable=False)
    value = Column(Text, nullable=False)
    extra_data = Column(JSON, default=dict)  # Renamed from 'metadata' (reserved word)
    
    # For vector search later
    embedding = Column(JSON, nullable=True)  # Store as JSON array for now
    
    created_at = Column(DateTime, default=datetime.utcnow)
    accessed_at = Column(DateTime, default=datetime.utcnow)
    access_count = Column(Integer, default=0)
    
    def __repr__(self):
        return f"<Memory {self.key[:30]}...>"


class ToolRegistry(Base):
    """Dynamically created tools (Agent Zero style)."""
    
    __tablename__ = "tools"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), unique=True, nullable=False)
    description = Column(Text)
    
    # Tool code (Python)
    code = Column(Text, nullable=False)
    
    # Execution stats
    times_used = Column(Integer, default=0)
    success_rate = Column(Float, default=1.0)
    
    # Trust
    created_by = Column(String(64), default="agent")
    is_verified = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    
    def __repr__(self):
        return f"<Tool {self.name}>"


# ═══════════════════════════════════════════════════════════════════════════════
# TRUST MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class TrustRecord(Base):
    """Trust level history for patterns."""
    
    __tablename__ = "trust_records"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    pattern = Column(String(256), nullable=False)  # e.g., "python:*.py"
    trust_level = Column(Enum(TrustLevel), default=TrustLevel.UNTRUSTED)
    
    # Stats
    consecutive_successes = Column(Integer, default=0)
    total_successes = Column(Integer, default=0)
    total_failures = Column(Integer, default=0)
    
    # Last action
    last_action = Column(String(32))  # success, failure, promotion, demotion
    last_action_reason = Column(Text, nullable=True)
    last_action_at = Column(DateTime, default=datetime.utcnow)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<TrustRecord {self.pattern}: {self.trust_level.value}>"


# ═══════════════════════════════════════════════════════════════════════════════
# LLM USAGE TRACKING
# ═══════════════════════════════════════════════════════════════════════════════

class LLMUsage(Base):
    """Track LLM usage for cost management."""
    
    __tablename__ = "llm_usage"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    provider = Column(Enum(LLMProvider), nullable=False)
    model = Column(String(64), nullable=True)
    
    # Usage
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    
    # Cost
    cost_usd = Column(Float, default=0.0)
    
    # Context
    task_id = Column(String(32), ForeignKey("tasks.id"), nullable=True)
    purpose = Column(String(128), nullable=True)  # "research", "code", "analysis"
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<LLMUsage {self.provider.value}: {self.total_tokens} tokens>"


# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE SETUP
# ═══════════════════════════════════════════════════════════════════════════════

def create_database(database_url: str = "sqlite:///./data/agentgrit.db") -> sessionmaker:
    """Create database and return session factory."""
    engine = create_engine(database_url, echo=False)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def get_session(database_url: str = "sqlite:///./data/agentgrit.db"):
    """Get a database session."""
    SessionFactory = create_database(database_url)
    return SessionFactory()


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def generate_task_id() -> str:
    """Generate a GRIT-prefixed task ID."""
    return f"GRIT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"


def get_daily_usage_summary(session, date: datetime | None = None) -> dict[str, Any]:
    """Get usage summary for a specific day."""
    from sqlalchemy import func
    
    date = date or datetime.utcnow()
    start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end = date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    usage = session.query(
        LLMUsage.provider,
        func.sum(LLMUsage.total_tokens).label("tokens"),
        func.sum(LLMUsage.cost_usd).label("cost"),
        func.count(LLMUsage.id).label("requests"),
    ).filter(
        LLMUsage.created_at >= start,
        LLMUsage.created_at <= end,
    ).group_by(LLMUsage.provider).all()
    
    return {
        row.provider.value: {
            "tokens": row.tokens or 0,
            "cost": row.cost or 0.0,
            "requests": row.requests or 0,
        }
        for row in usage
    }
