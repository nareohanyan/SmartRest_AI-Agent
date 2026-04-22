from __future__ import annotations

from typing import Any, Protocol


class RuntimePolicyError(RuntimeError):
    """Raised when the configured runtime policy is unsafe for the selected environment."""


class _RuntimeSettings(Protocol):
    app_env: Any
    auth_secret_key: str | None
    openai_api_key: str | None
    planner_mode: Any
    database_url: str | None
    chat_analytics_database_url: str | None
    scope_backend_mode: Any
    report_backend_mode: Any
    analytics_backend_mode: Any


_STRICT_RUNTIME_ENVS = {"local_acceptance", "staging", "production"}
_STRICT_BACKEND_FIELDS = (
    "scope_backend_mode",
    "report_backend_mode",
    "analytics_backend_mode",
)


def is_strict_runtime_environment(app_env: str) -> bool:
    return app_env in _STRICT_RUNTIME_ENVS


def validate_runtime_settings(settings: _RuntimeSettings) -> None:
    """Fail fast when a non-development environment is configured unsafely."""
    if not is_strict_runtime_environment(settings.app_env):
        return

    issues: list[str] = []
    if not _is_non_empty(settings.auth_secret_key):
        issues.append("auth secret key is required")

    if not _is_non_empty(settings.database_url):
        issues.append("SMARTREST_DATABASE_URL is required")

    if not _is_non_empty(settings.chat_analytics_database_url):
        issues.append("SMARTREST_CHAT_ANALYTICS_DATABASE_URL is required")

    if settings.planner_mode != "deterministic" and not _is_non_empty(settings.openai_api_key):
        issues.append(
            "OpenAI API key is required when planner_mode is not deterministic"
        )

    for field_name in _STRICT_BACKEND_FIELDS:
        if getattr(settings, field_name) != "db_strict":
            issues.append(f"{field_name} must be db_strict")

    if not issues:
        return

    raise RuntimePolicyError(
        "Unsafe runtime policy for environment "
        f"`{settings.app_env}`: {'; '.join(issues)}."
    )


def require_strict_backend_mode(
    *,
    settings: _RuntimeSettings,
    field_name: str,
    actual_mode: str,
) -> None:
    """Guard direct tool usage from silently enabling demo behavior in strict runtimes."""
    app_env = getattr(settings, "app_env", "development")
    if not is_strict_runtime_environment(app_env):
        return

    if actual_mode == "db_strict":
        return

    raise RuntimePolicyError(
        f"Environment `{app_env}` requires {field_name}=db_strict, "
        f"got `{actual_mode}`."
    )


def _is_non_empty(value: str | None) -> bool:
    return value is not None and bool(value.strip())
