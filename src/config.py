"""AgentGRIT Configuration Module

Centralized configuration using Pydantic Settings.
Loads from environment variables and .env file.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """AgentGRIT configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # =========================================================================
    # CORE AI CONFIGURATION
    # =========================================================================
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    pplx_api_key: str = Field(default="", description="Perplexity API key (research/web-search tier)")

    # Ollama (cost-first default -- FREE and unlimited)
    ollama_base_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="gemma4:12b")
    ollama_enabled: bool = Field(default=True)

    # Model selection
    primary_model: str = Field(default="claude-sonnet-4-20250514")
    complex_model: str = Field(default="claude-opus-4-5-20250514")
    simple_model: str = Field(default="claude-haiku-4-5-20250514")

    # =========================================================================
    # TELEGRAM BOT (optional control plane -- leave blank to skip)
    # =========================================================================
    telegram_bot_token: str = Field(default="", description="Telegram bot token")
    telegram_admin_ids: str = Field(default="", description="Comma-separated admin user IDs")
    telegram_notification_chat_id: str = Field(default="")

    @property
    def admin_ids(self) -> list[int]:
        """Parse admin IDs from comma-separated string. Ignores non-numeric values."""
        if not self.telegram_admin_ids:
            return []
        result = []
        for uid in self.telegram_admin_ids.split(","):
            uid = uid.strip()
            if uid and uid.isdigit():
                result.append(int(uid))
        return result

    # =========================================================================
    # DATABASE & CACHE
    # =========================================================================
    database_url: str = Field(default="sqlite+aiosqlite:///./data/agentgrit.db")
    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_enabled: bool = Field(default=True)

    # =========================================================================
    # API SERVER
    # =========================================================================
    api_host: str = Field(default="127.0.0.1")  # loopback by default; opt into 0.0.0.0 explicitly for network exposure (see SECURITY.md)
    api_port: int = Field(default=8000)
    api_reload: bool = Field(default=False)
    api_secret_key: str = Field(default="change-me-in-production")
    cors_origins: str = Field(default="http://localhost:3000")

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse CORS origins from comma-separated string."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    # =========================================================================
    # EXECUTION
    # =========================================================================
    dry_run: bool = Field(default=True, description="Agents log actions but don't execute them")

    # =========================================================================
    # LOGGING
    # =========================================================================
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    log_dir: str = Field(default="./logs")
    log_format: Literal["json", "console"] = Field(default="json")

    @property
    def log_path(self) -> Path:
        """Get log directory path."""
        path = Path(self.log_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    # =========================================================================
    # GOVERNANCE
    # =========================================================================
    trust_promote_threshold: int = Field(default=5)
    trust_autonomous_threshold: int = Field(default=20)
    cost_escalation_threshold: float = Field(default=1.00)
    digest_interval_hours: int = Field(default=4)

    # =========================================================================
    # SECURITY
    # =========================================================================
    encryption_key: str = Field(default="")
    session_timeout: int = Field(default=3600)

    # =========================================================================
    # VALIDATION
    # =========================================================================
    @field_validator("anthropic_api_key")
    @classmethod
    def validate_anthropic_key(cls, v: str) -> str:
        """Validate Anthropic API key format."""
        if v and not v.startswith("sk-ant-"):
            raise ValueError("Anthropic API key must start with 'sk-ant-'")
        return v

    def is_configured(self) -> bool:
        """Check if minimum required configuration is present."""
        return bool(self.anthropic_api_key or self.ollama_enabled)

    def get_active_backend(self) -> Literal["anthropic", "ollama"]:
        """Determine which AI backend to use.

        Cost-first: prefer Ollama (free) when available.
        Claude is the fallback for complex tasks, not the default.
        """
        if self.ollama_enabled:
            return "ollama"
        if self.anthropic_api_key:
            return "anthropic"
        raise ValueError("No AI backend configured. Enable OLLAMA or set ANTHROPIC_API_KEY.")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience alias
settings = get_settings()
