from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.auth import (
    build_canonical_payload,
    build_platform_admin_canonical_payload,
    sign_payload_token,
    verify_platform_admin_payload,
    verify_signed_payload,
)
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_verify_signed_payload_accepts_valid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMARTREST_AUTH_SECRET_KEY", "test-secret")
    monkeypatch.setenv("SMARTREST_AUTH_TOKEN_MAX_AGE_SECONDS", "300")
    monkeypatch.setenv("SMARTREST_AUTH_TOKEN_MAX_FUTURE_SKEW_SECONDS", "30")

    current_timestamp = 1_700_000_000
    canonical_payload = build_canonical_payload(
        current_timestamp=current_timestamp,
        profile_nick="nick",
        profile_id=201,
        user_id=101,
    )
    token = sign_payload_token("test-secret", canonical_payload)
    monkeypatch.setattr("app.core.auth.time.time", lambda: current_timestamp + 10)

    verified = verify_signed_payload(
        profile_nick="nick",
        user_id=101,
        profile_id=201,
        current_timestamp=current_timestamp,
        token=token,
        request_id="req-1",
    )

    assert verified.profile_nick == "nick"
    assert verified.user_id == 101
    assert verified.profile_id == 201


def test_verify_signed_payload_rejects_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMARTREST_AUTH_SECRET_KEY", "test-secret")
    monkeypatch.setattr("app.core.auth.time.time", lambda: 1_700_000_000)

    with pytest.raises(HTTPException) as exc_info:
        verify_signed_payload(
            profile_nick="nick",
            user_id=101,
            profile_id=201,
            current_timestamp=1_700_000_000,
            token="0" * 64,
            request_id="req-2",
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Unauthorized"


def test_verify_signed_payload_rejects_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMARTREST_AUTH_SECRET_KEY", "test-secret")
    monkeypatch.setenv("SMARTREST_AUTH_TOKEN_MAX_AGE_SECONDS", "300")
    monkeypatch.setattr("app.core.auth.time.time", lambda: 1_700_000_500)

    canonical_payload = build_canonical_payload(
        current_timestamp=1_700_000_000,
        profile_nick="nick",
        profile_id=201,
        user_id=101,
    )
    token = sign_payload_token("test-secret", canonical_payload)

    with pytest.raises(HTTPException) as exc_info:
        verify_signed_payload(
            profile_nick="nick",
            user_id=101,
            profile_id=201,
            current_timestamp=1_700_000_000,
            token=token,
            request_id="req-3",
        )

    assert exc_info.value.status_code == 401


def test_verify_signed_payload_rejects_future_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMARTREST_AUTH_SECRET_KEY", "test-secret")
    monkeypatch.setenv("SMARTREST_AUTH_TOKEN_MAX_FUTURE_SKEW_SECONDS", "30")
    monkeypatch.setattr("app.core.auth.time.time", lambda: 1_700_000_000)

    canonical_payload = build_canonical_payload(
        current_timestamp=1_700_000_100,
        profile_nick="nick",
        profile_id=201,
        user_id=101,
    )
    token = sign_payload_token("test-secret", canonical_payload)

    with pytest.raises(HTTPException) as exc_info:
        verify_signed_payload(
            profile_nick="nick",
            user_id=101,
            profile_id=201,
            current_timestamp=1_700_000_100,
            token=token,
            request_id="req-4",
        )

    assert exc_info.value.status_code == 401


def test_verify_signed_payload_requires_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.auth.get_settings",
        lambda: SimpleNamespace(
            auth_secret_key=None,
            auth_token_max_age_seconds=300,
            auth_token_max_future_skew_seconds=30,
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        verify_signed_payload(
            profile_nick="nick",
            user_id=101,
            profile_id=201,
            current_timestamp=1_700_000_000,
            token="0" * 64,
            request_id="req-5",
        )

    assert exc_info.value.status_code == 500


def test_verify_platform_admin_payload_accepts_valid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMARTREST_PLATFORM_ADMIN_SECRET_KEY", "admin-secret")
    monkeypatch.setenv("SMARTREST_AUTH_TOKEN_MAX_AGE_SECONDS", "300")
    monkeypatch.setenv("SMARTREST_AUTH_TOKEN_MAX_FUTURE_SKEW_SECONDS", "30")

    current_timestamp = 1_700_000_000
    canonical_payload = build_platform_admin_canonical_payload(
        current_timestamp=current_timestamp,
        admin_id="owner",
    )
    token = sign_payload_token("admin-secret", canonical_payload)
    monkeypatch.setattr("app.core.auth.time.time", lambda: current_timestamp + 10)

    verified = verify_platform_admin_payload(
        admin_id="owner",
        current_timestamp=current_timestamp,
        token=token,
        request_id="req-admin-1",
    )

    assert verified.admin_id == "owner"


def test_verify_platform_admin_payload_rejects_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMARTREST_PLATFORM_ADMIN_SECRET_KEY", "admin-secret")
    monkeypatch.setattr("app.core.auth.time.time", lambda: 1_700_000_000)

    with pytest.raises(HTTPException) as exc_info:
        verify_platform_admin_payload(
            admin_id="owner",
            current_timestamp=1_700_000_000,
            token="0" * 64,
            request_id="req-admin-2",
        )

    assert exc_info.value.status_code == 401


def test_verify_platform_admin_payload_requires_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.core.auth.get_settings",
        lambda: SimpleNamespace(
            platform_admin_secret_key=None,
            auth_token_max_age_seconds=300,
            auth_token_max_future_skew_seconds=30,
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        verify_platform_admin_payload(
            admin_id="owner",
            current_timestamp=1_700_000_000,
            token="0" * 64,
            request_id="req-admin-3",
        )

    assert exc_info.value.status_code == 500
