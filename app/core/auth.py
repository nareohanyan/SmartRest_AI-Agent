from __future__ import annotations

import hashlib
import logging
import re
import secrets
import time
from dataclasses import dataclass

from fastapi import HTTPException

from app.core.config import get_settings

logger = logging.getLogger(__name__)
_HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UNAUTHORIZED = HTTPException(status_code=401, detail="Unauthorized")


@dataclass(frozen=True)
class VerifiedIdentity:
    profile_nick: str
    user_id: int
    profile_id: int


def build_canonical_payload(
    *,
    current_timestamp: int,
    profile_nick: str,
    profile_id: int,
    user_id: int,
) -> str:
    return f"{current_timestamp}-{profile_nick}-{profile_id}-{user_id}"


def sign_payload_token(secret_key: str, canonical_payload: str) -> str:
    return hashlib.sha256(f"{secret_key}-{canonical_payload}".encode()).hexdigest()


def verify_signed_payload(
    *,
    profile_nick: str,
    user_id: int,
    profile_id: int,
    current_timestamp: int,
    token: str,
    request_id: str,
) -> VerifiedIdentity:
    settings = get_settings()

    if not profile_nick or not isinstance(profile_nick, str):
        _log_auth_failure(request_id=request_id, reason="missing_profile_nick")
        raise _UNAUTHORIZED

    if not _HEX_SHA256_RE.fullmatch(token or ""):
        _log_auth_failure(request_id=request_id, reason="invalid_token_format")
        raise _UNAUTHORIZED

    secret = settings.auth_secret_key
    if not secret:
        raise HTTPException(status_code=500, detail="Auth secret key is not configured")

    now_ts = int(time.time())
    max_age = settings.auth_token_max_age_seconds
    max_future_skew = settings.auth_token_max_future_skew_seconds

    if (now_ts - current_timestamp) > max_age:
        _log_auth_failure(request_id=request_id, reason="expired")
        raise _UNAUTHORIZED

    if (current_timestamp - now_ts) > max_future_skew:
        _log_auth_failure(request_id=request_id, reason="future_timestamp")
        raise _UNAUTHORIZED

    canonical = build_canonical_payload(
        current_timestamp=current_timestamp,
        profile_nick=profile_nick,
        profile_id=profile_id,
        user_id=user_id,
    )
    expected = sign_payload_token(secret_key=secret, canonical_payload=canonical)
    if not secrets.compare_digest(token, expected):
        _log_auth_failure(request_id=request_id, reason="invalid_token")
        raise _UNAUTHORIZED

    return VerifiedIdentity(
        profile_nick=profile_nick,
        user_id=user_id,
        profile_id=profile_id,
    )


def _log_auth_failure(*, request_id: str, reason: str) -> None:
    logger.warning("auth_failed request_id=%s reason=%s", request_id or "-", reason)
