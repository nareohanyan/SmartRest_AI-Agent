"""Application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings loaded from environment."""

    app_name: str = "SmartRest AI Agent"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "SMARTREST_OPENAI_API_KEY",
            "OPENAI_API_KEY"
        )
    )
    openai_model: str = "gpt-4.1-mini"
    openai_timeout_seconds: float = 15.0
    openai_retry_max_attempts: int = 3
    openai_retry_initial_delay_seconds: float = 0.2
    openai_retry_max_delay_seconds: float = 2.0
    auth_secret_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SMARTREST_AUTH_SECRET_KEY", "SECRET_KEY"),
    )
    auth_token_max_age_seconds: int = 300
    auth_token_max_future_skew_seconds: int = 30

    planner_mode: Literal["deterministic", "hybrid", "llm"] = "hybrid"
    planner_min_confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    planner_max_date_range_days: int = Field(default=366, ge=1, le=3660)
    planner_max_tool_calls: int = Field(default=6, ge=1, le=20)
    planner_allow_safe_general_topics: bool = True
    planner_fallback_enabled: bool = True

    database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SMARTREST_DATABASE_URL", "DATABASE_URL"),
    )
    chat_analytics_database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "SMARTREST_CHAT_ANALYTICS_DATABASE_URL",
            "CHAT_ANALYTICS_DATABASE_URL",
        ),
    )
    toon_lahmajo_db_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "SMARTREST_TOON_LAHMAJO_DB",
            "TOON_LAHMAJO_DB",
        ),
    )
    scope_backend_mode: Literal["mock", "db_with_fallback", "db_strict"] = "mock"
    report_backend_mode: Literal["mock", "db_with_fallback", "db_strict"] = "mock"
    analytics_backend_mode: Literal["mock", "db_with_fallback", "db_strict"] = "mock"
    sync_batch_size_profiles: int = Field(default=1000, ge=1, le=50_000)
    sync_batch_size_users: int = Field(default=2000, ge=1, le=50_000)
    sync_batch_size_tables: int = Field(default=1000, ge=1, le=50_000)
    sync_source_system_server_name: str = "toon_lahmajo"
    sync_source_system_cloud_num: int = 1

    model_config = SettingsConfigDict(
        env_prefix="SMARTREST_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
