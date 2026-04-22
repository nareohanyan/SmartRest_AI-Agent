from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy.orm import Session

from app.core.auth import VerifiedIdentity
from app.schemas.subscription import AIAgentSubscriptionStatus, SubscriptionAccessDecision
from app.smartrest.models import Profile, get_sync_session_factory

_ALLOWED_STATUSES = {
    AIAgentSubscriptionStatus.ACTIVE,
    AIAgentSubscriptionStatus.TRIAL,
}


class SubscriptionAccessServiceError(RuntimeError):
    pass


class SubscriptionAccessService:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        self._session_factory = session_factory or get_sync_session_factory()

    def evaluate_access(self, verified_identity: VerifiedIdentity) -> SubscriptionAccessDecision:
        try:
            session = self._session_factory()
        except Exception as exc:
            raise SubscriptionAccessServiceError("Subscription access check failed.") from exc

        try:
            profile = session.get(Profile, verified_identity.profile_id)
        except Exception as exc:
            raise SubscriptionAccessServiceError("Subscription access check failed.") from exc
        finally:
            session.close()

        if profile is None:
            return SubscriptionAccessDecision(
                allowed=False,
                reason_code="profile_not_found",
                reason_message="AI agent subscription profile was not found.",
            )

        raw_status = profile.ai_agent_subscription_status or AIAgentSubscriptionStatus.EXPIRED.value
        try:
            status = AIAgentSubscriptionStatus(raw_status)
        except ValueError:
            return SubscriptionAccessDecision(
                allowed=False,
                reason_code="subscription_invalid_status",
                reason_message="AI agent subscription status is invalid.",
            )

        if status not in _ALLOWED_STATUSES:
            return SubscriptionAccessDecision(
                allowed=False,
                reason_code=f"subscription_{status.value}",
                reason_message="AI agent subscription is inactive.",
            )

        expires_at = profile.ai_agent_subscription_expires_at
        if isinstance(expires_at, datetime):
            normalized_expires_at = _normalize_datetime(expires_at)
            if normalized_expires_at <= datetime.now(timezone.utc):
                return SubscriptionAccessDecision(
                    allowed=False,
                    reason_code="subscription_expired",
                    reason_message="AI agent subscription is inactive.",
                )

        return SubscriptionAccessDecision(
            allowed=True,
            reason_code="subscription_allowed",
            reason_message="AI agent subscription is active.",
        )


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@lru_cache(maxsize=1)
def get_subscription_access_service() -> SubscriptionAccessService:
    return SubscriptionAccessService()
