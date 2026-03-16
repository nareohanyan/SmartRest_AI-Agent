"""Application configuration."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings loaded from environment."""

    app_name: str = "SmartRest AI Agent"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = 15.0
    openai_retry_max_attempts: int = 3
    openai_retry_initial_delay_seconds: float = 0.2
    openai_retry_max_delay_seconds: float = 2.0

    model_config = SettingsConfigDict(
        env_prefix="SMARTREST_",
        env_file=".env",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
