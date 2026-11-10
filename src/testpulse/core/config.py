"""
TestPulse — Core Configuration
Loaded from .env via pydantic-settings. All runtime parameters are defined here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Centralised configuration for the TestPulse platform.

    All values are read from environment variables or a .env file in the
    project root. See .env.example for the full list of configurable keys.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="TESTPULSE_",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Server
    # ------------------------------------------------------------------
    host: str = Field(default="127.0.0.1", alias="TESTPULSE_HOST")
    port: int = Field(default=8000, alias="TESTPULSE_PORT")
    env: str = Field(default="development", alias="TESTPULSE_ENV")
    log_level: str = Field(default="INFO", alias="TESTPULSE_LOG_LEVEL")

    # ------------------------------------------------------------------
    # Storage paths
    # ------------------------------------------------------------------
    workspace_dir: Path = Field(
        default=Path(".testpulse"), alias="TESTPULSE_WORKSPACE_DIR"
    )
    db_path: Path = Field(
        default=Path(".testpulse/testpulse.db"), alias="TESTPULSE_DB_PATH"
    )
    qdrant_path: Path = Field(
        default=Path(".testpulse/qdrant"), alias="TESTPULSE_QDRANT_PATH"
    )

    # ------------------------------------------------------------------
    # OpenRouter / LLM Gateway
    # ------------------------------------------------------------------
    openrouter_api_key: str = Field(
        default="", alias="OPENROUTER_API_KEY"
    )

    tier1_models_raw: str = Field(
        default="nvidia/nemotron-3-ultra:free",
        alias="TESTPULSE_TIER1_MODELS",
    )
    tier2_models_raw: str = Field(
        default="nvidia/nemotron-3.5-lightning:free",
        alias="TESTPULSE_TIER2_MODELS",
    )

    llm_max_retries: int = Field(default=3, alias="TESTPULSE_LLM_MAX_RETRIES")
    llm_timeout_seconds: int = Field(
        default=120, alias="TESTPULSE_LLM_TIMEOUT_SECONDS"
    )

    # ------------------------------------------------------------------
    # Embedding (remote API, zero host RAM)
    # ------------------------------------------------------------------
    embedding_model: str = Field(
        default="openai/text-embedding-3-small",
        alias="TESTPULSE_EMBEDDING_MODEL",
    )
    embedding_api_key: str = Field(
        default="", alias="TESTPULSE_EMBEDDING_API_KEY"
    )
    embedding_base_url: str | None = Field(
        default=None, alias="TESTPULSE_EMBEDDING_BASE_URL"
    )
    embedding_batch_size: int = Field(
        default=32, alias="TESTPULSE_EMBEDDING_BATCH_SIZE"
    )

    # ------------------------------------------------------------------
    # Test pipeline
    # ------------------------------------------------------------------
    max_targets: Annotated[int, Field(ge=1, le=50)] = Field(
        default=5, alias="TESTPULSE_MAX_TARGETS"
    )
    max_repair_retries: Annotated[int, Field(ge=1, le=10)] = Field(
        default=3, alias="TESTPULSE_MAX_REPAIR_RETRIES"
    )
    sandbox_timeout_seconds: int = Field(
        default=30, alias="TESTPULSE_SANDBOX_TIMEOUT_SECONDS"
    )
    sandbox_memory_limit: str = Field(
        default="2048m", alias="TESTPULSE_SANDBOX_MEMORY_LIMIT"
    )

    # ------------------------------------------------------------------
    # MCP Server
    # ------------------------------------------------------------------
    mcp_transport: str = Field(default="stdio", alias="TESTPULSE_MCP_TRANSPORT")

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------
    @property
    def tier1_models(self) -> list[str]:
        """Ordered list of Tier 1 (high-thinking) model slugs."""
        return [m.strip() for m in self.tier1_models_raw.split(",") if m.strip()]

    @property
    def tier2_models(self) -> list[str]:
        """Ordered list of Tier 2 (fast utility) model slugs."""
        return [m.strip() for m in self.tier2_models_raw.split(",") if m.strip()]

    @property
    def db_url(self) -> str:
        """SQLAlchemy async connection string for SQLite."""
        return f"sqlite+aiosqlite:///{self.db_path}"

    @field_validator("workspace_dir", "db_path", "qdrant_path", mode="before")
    @classmethod
    def resolve_path(cls, v: str | Path) -> Path:
        """Expand user home and resolve relative paths."""
        return Path(v).expanduser()

    def ensure_workspace(self) -> None:
        """Create workspace directories if they don't exist."""
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.qdrant_path.mkdir(parents=True, exist_ok=True)


# Singleton — import and use `settings` throughout the codebase.
settings = Settings()
