"""
AgentGRIT API Server

FastAPI server providing:
- Health checks and metrics
- Task management endpoints
- Webhook integrations
"""

import asyncio
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import structlog

from ..config import settings
from ..governance.bylaws import get_bylaw_engine
from ..governance.trust import get_trust_manager
from ..execution.claude_client import get_execution_manager


# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer() if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════════════════════


class HealthResponse(BaseModel):
    """Health check response."""
    
    status: str
    version: str
    uptime_seconds: float
    services: dict[str, bool]
    timestamp: str


class TaskSpawnRequest(BaseModel):
    """Request to spawn a new agent task."""
    
    description: str = Field(..., description="Task description")
    priority: str = Field("normal", description="Priority: low, normal, high")
    project: str = Field("default", description="Target project")
    context: dict[str, Any] = Field(default_factory=dict, description="Additional context")


class TaskResponse(BaseModel):
    """Response for task operations."""
    
    task_id: str
    status: str
    description: str
    created_at: str
    message: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# LIFESPAN & APP SETUP
# ═══════════════════════════════════════════════════════════════════════════════

_startup_time: datetime | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global _startup_time
    
    logger.info("Starting AgentGRIT API server")
    _startup_time = datetime.utcnow()
    
    execution_manager = get_execution_manager()
    await execution_manager.initialize()
    
    health = await execution_manager.health_check()
    logger.info("Service health", **health)
    
    yield
    
    logger.info("Shutting down AgentGRIT API server")


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH -- fail closed: no key + non-loopback host is refused (see SECURITY.md)
# ═══════════════════════════════════════════════════════════════════════════════
_OPEN_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


async def require_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    """Gate every non-open endpoint.

    - Open paths (/health, docs) are always reachable.
    - If API_SECRET_KEY is set, a matching X-API-Key header is required.
    - If no key is set, access is allowed ONLY on a loopback host; binding to a
      non-loopback host without a key is refused (fail closed). See SECURITY.md.
    """
    if request.url.path in _OPEN_PATHS:
        return
    configured = (getattr(settings, "api_secret_key", "") or "").strip()
    if not configured:
        host = (getattr(settings, "api_host", "") or "").strip()
        if host in _LOOPBACK_HOSTS:
            return
        raise HTTPException(
            status_code=503,
            detail="API_SECRET_KEY must be set when binding to a non-loopback "
                   "host (see SECURITY.md).",
        )
    if not x_api_key or not secrets.compare_digest(x_api_key, configured):
        raise HTTPException(status_code=401, detail="Missing or invalid API key.")


app = FastAPI(
    title="AgentGRIT API",
    description="Self-governing AI agent orchestration API",
    version="2.0.0",
    lifespan=lifespan,
    dependencies=[Depends(require_api_key)],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH & STATUS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check() -> HealthResponse:
    """System health check."""
    manager = get_execution_manager()
    health = await manager.health_check()
    
    uptime = 0.0
    if _startup_time:
        uptime = (datetime.utcnow() - _startup_time).total_seconds()
    
    return HealthResponse(
        status="healthy" if any(health.values()) else "degraded",
        version="2.0.0",
        uptime_seconds=uptime,
        services=health,
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@app.get("/status", tags=["System"])
async def system_status() -> dict[str, Any]:
    """Detailed system status."""
    trust_manager = get_trust_manager()
    stats = trust_manager.get_statistics()
    
    # Research knowledge cache lives on disk (logs/knowledge.jsonl); count it
    # honestly instead of referencing an in-memory cache that does not exist.
    kb = Path(__file__).resolve().parents[2] / "logs" / "knowledge.jsonl"
    try:
        cache_entries = sum(1 for _ in kb.open()) if kb.exists() else 0
    except Exception:
        cache_entries = 0

    return {
        "version": "2.0.0",
        "trust_statistics": stats,
        "cache_entries": cache_entries,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TASK MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/tasks/spawn", response_model=TaskResponse, tags=["Tasks"])
async def spawn_task(request: TaskSpawnRequest) -> TaskResponse:
    """Spawn a new agent task."""
    task_id = f"GRIT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    
    # TODO: Actually spawn task via orchestrator
    
    logger.info("Task spawned", task_id=task_id, description=request.description)
    
    return TaskResponse(
        task_id=task_id,
        status="queued",
        description=request.description,
        created_at=datetime.utcnow().isoformat() + "Z",
        message="Task queued for execution",
    )


@app.get("/tasks/{task_id}", response_model=TaskResponse, tags=["Tasks"])
async def get_task(task_id: str) -> TaskResponse:
    """Get task status."""
    # TODO: Look up actual task
    
    return TaskResponse(
        task_id=task_id,
        status="running",
        description="Task description",
        created_at=datetime.utcnow().isoformat() + "Z",
    )


@app.get("/tasks", tags=["Tasks"])
async def list_tasks(status: str | None = None, limit: int = 20) -> dict[str, Any]:
    """List tasks with optional filtering."""
    # TODO: Get actual tasks from database
    
    return {
        "tasks": [],
        "total": 0,
        "filter": {"status": status, "limit": limit},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# GOVERNANCE
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/governance/trust", tags=["Governance"])
async def get_trust_levels() -> dict[str, Any]:
    """Get trust level statistics."""
    manager = get_trust_manager()
    return manager.get_statistics()


@app.get("/governance/suggestions", tags=["Governance"])
async def get_bylaw_suggestions() -> dict[str, Any]:
    """Get suggested bylaw updates based on patterns."""
    manager = get_trust_manager()
    suggestions = manager.suggest_bylaw_updates()
    
    return {
        "suggestions": suggestions,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# OBSERVE — scored live-data view (auth same as rest of API)
# ═══════════════════════════════════════════════════════════════════════════════

# Last fused+gated snapshot (in-process). Observation never acts.
_last_observe: dict[str, Any] | None = None


@app.get("/observe/view", tags=["Observe"])
async def observe_view(
    feed: str | None = None,
    refresh: bool = False,
    fixture: bool = False,
) -> dict[str, Any]:
    """Return fused, evidence-scored observations.

    - refresh=true: re-fetch (live keyless feeds, or fixtures if fixture=true)
    - default: return last snapshot; if none, run once offline-safe on empty

    Does not execute actions. Auth: same fail-closed API key gate as other routes.
    """
    global _last_observe
    try:
        from src.observe.run import run_observe
        from pathlib import Path

        if refresh or _last_observe is None:
            fixture_dir = None
            if fixture:
                fixture_dir = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "observe"
            result, _text = run_observe(
                feed=feed,
                fixture_dir=fixture_dir,
                record_decision=True,
            )
            _last_observe = {
                "ts": datetime.utcnow().isoformat() + "Z",
                "feed": feed or "all",
                "result": result.to_dict(),
            }
        return _last_observe or {
            "ts": datetime.utcnow().isoformat() + "Z",
            "feed": feed or "all",
            "result": {"events": [], "assessment_verdict": "insufficient"},
        }
    except Exception as e:
        logger.warning("observe_view failed", error=str(e))
        raise HTTPException(status_code=500, detail="observe failed safe") from e


def _set_last_observe_for_tests(payload: dict[str, Any] | None) -> None:
    """Test helper — inject a snapshot without network."""
    global _last_observe
    _last_observe = payload


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ═══════════════════════════════════════════════════════════════════════════════

def run_server():
    """Run the API server."""
    import uvicorn
    
    uvicorn.run(
        "src.api.server:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run_server()
