"""Application configuration."""

from functools import lru_cache

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

    model_config = SettingsConfigDict(
        env_prefix="SMARTREST_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
