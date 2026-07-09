"""
Application configuration.

All runtime settings are read from environment variables (with sensible defaults
for local development). The .env file at the project root is loaded automatically
by pydantic-settings.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    """Strongly-typed app configuration."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Database ----
    # SQLite for local dev (default); Postgres URL for production, e.g.
    #   postgresql+psycopg://readonly_user:***@host:5432/dbname
    # NOTE: env var is ECOM_DB_URL (not DATABASE_URL) to avoid clashing with
    # other tools in the same environment.
    database_url: str = Field(
        default=f"sqlite:///{BACKEND_ROOT / 'data' / 'ecommerce.db'}",
        alias="ECOM_DB_URL",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_sqlite_path(cls, value: str | Path) -> str | Path:
        if not isinstance(value, str):
            return value

        if value.startswith("sqlite:///"):
            path_part = value.removeprefix("sqlite:///")
            if not path_part.startswith("/"):
                resolved_path = (PROJECT_ROOT / path_part).resolve()
                return f"sqlite:///{resolved_path}"

        return value

    # When True, the connection is opened in read-only mode at the driver level.
    # This is a defense-in-depth measure on top of the AST validator — even if
    # the validator were bypassed, the DB itself would reject any write.
    db_read_only: bool = True

    # Hard cap on rows returned by any executed query, regardless of what the
    # LLM generates. The validator injects LIMIT if missing, and shrinks LIMIT
    # if the LLM asks for more.
    query_row_limit: int = 1000

    # Hard execution timeout (seconds) enforced at the driver level.
    query_timeout_seconds: float = 5.0

      # ---- LLM ----
    # "gemini" (Google free tier — recommended for deployment)
    # "claude" (architecture.md default, needs ANTHROPIC_API_KEY)
    # "glm" (z-ai CLI, local dev only — doesn't work on servers)
    llm_provider: str = "glm"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5-20250929"

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"

    # Maximum number of self-correction attempts before giving up.
    # Architecture.md mandates a hard cap of 3.
    max_correction_attempts: int = 3

    # ---- App ----
    app_name: str = "NL-to-SQL Analytics Copilot"
    debug: bool = True


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
