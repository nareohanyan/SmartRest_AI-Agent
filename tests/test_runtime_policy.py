from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.runtime_policy import (
    RuntimePolicyError,
    is_strict_runtime_environment,
    require_strict_backend_mode,
    validate_runtime_settings,
)


def _settings(**overrides: object) -> SimpleNamespace:
    payload = {
        "app_env": "development",
        "auth_secret_key": "test-secret",
        "openai_api_key": "test-openai-key",
        "planner_mode": "hybrid",
        "database_url": "postgresql+psycopg://user:pass@localhost:5432/smartrest",
        "chat_analytics_database_url": (
            "postgresql+psycopg://user:pass@localhost:5432/chat_analytics_db"
        ),
        "scope_backend_mode": "db_strict",
        "report_backend_mode": "db_strict",
        "analytics_backend_mode": "db_strict",
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


@pytest.mark.parametrize("app_env", ["local_acceptance", "staging", "production"])
def test_strict_runtime_environment_detection(app_env: str) -> None:
    assert is_strict_runtime_environment(app_env) is True


def test_development_runtime_environment_is_not_strict() -> None:
    assert is_strict_runtime_environment("development") is False


def test_validate_runtime_settings_allows_development_fallback_modes() -> None:
    validate_runtime_settings(
        _settings(
            app_env="development",
            scope_backend_mode="mock",
            report_backend_mode="db_with_fallback",
            analytics_backend_mode="mock",
            auth_secret_key=None,
            openai_api_key=None,
            database_url=None,
            chat_analytics_database_url=None,
        )
    )


def test_validate_runtime_settings_rejects_non_strict_backends_in_strict_env() -> None:
    with pytest.raises(RuntimePolicyError, match="scope_backend_mode must be db_strict"):
        validate_runtime_settings(
            _settings(
                app_env="staging",
                scope_backend_mode="db_with_fallback",
            )
        )


def test_validate_runtime_settings_requires_runtime_dependencies_in_strict_env() -> None:
    with pytest.raises(RuntimePolicyError, match="auth secret key is required"):
        validate_runtime_settings(
            _settings(
                app_env="production",
                auth_secret_key=None,
                database_url=None,
                chat_analytics_database_url=None,
            )
        )


def test_validate_runtime_settings_allows_deterministic_planner_without_openai() -> None:
    validate_runtime_settings(
        _settings(
            app_env="local_acceptance",
            planner_mode="deterministic",
            openai_api_key=None,
        )
    )


def test_require_strict_backend_mode_rejects_unsafe_backend_in_strict_env() -> None:
    with pytest.raises(RuntimePolicyError, match="report_backend_mode=db_strict"):
        require_strict_backend_mode(
            settings=_settings(app_env="staging"),
            field_name="report_backend_mode",
            actual_mode="db_with_fallback",
        )


def test_require_strict_backend_mode_allows_development_mock_mode() -> None:
    require_strict_backend_mode(
        settings=_settings(app_env="development"),
        field_name="analytics_backend_mode",
        actual_mode="mock",
    )
