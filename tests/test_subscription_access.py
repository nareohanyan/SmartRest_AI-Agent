from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.auth import VerifiedIdentity
from app.schemas.subscription import AIAgentSubscriptionStatus
from app.services.subscription_access import SubscriptionAccessService
from app.smartrest.models import Profile

_VERIFIED_IDENTITY = VerifiedIdentity(profile_nick="nick", user_id=101, profile_id=201)


@pytest.fixture
def subscription_engine() -> Iterator[object]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Profile.__table__.create(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def subscription_service(subscription_engine: object) -> SubscriptionAccessService:
    def _session_factory() -> Session:
        return Session(
            bind=subscription_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    return SubscriptionAccessService(session_factory=_session_factory)


def _insert_profile(
    subscription_engine: object,
    *,
    status: AIAgentSubscriptionStatus,
    expires_at: datetime | None = None,
) -> None:
    with Session(bind=subscription_engine) as session:
        session.add(
            Profile(
                id=201,
                name="Nick",
                ai_agent_subscription_status=status.value,
                ai_agent_subscription_expires_at=expires_at,
            )
        )
        session.commit()


@pytest.mark.parametrize(
    "status",
    [AIAgentSubscriptionStatus.ACTIVE, AIAgentSubscriptionStatus.TRIAL],
)
def test_subscription_service_allows_active_and_trial_statuses(
    subscription_engine: object,
    subscription_service: SubscriptionAccessService,
    status: AIAgentSubscriptionStatus,
) -> None:
    _insert_profile(subscription_engine, status=status)

    decision = subscription_service.evaluate_access(_VERIFIED_IDENTITY)

    assert decision.allowed is True
    assert decision.reason_code == "subscription_allowed"


@pytest.mark.parametrize(
    "status",
    [
        AIAgentSubscriptionStatus.EXPIRED,
        AIAgentSubscriptionStatus.CANCELLED,
        AIAgentSubscriptionStatus.SUSPENDED,
    ],
)
def test_subscription_service_denies_inactive_statuses(
    subscription_engine: object,
    subscription_service: SubscriptionAccessService,
    status: AIAgentSubscriptionStatus,
) -> None:
    _insert_profile(subscription_engine, status=status)

    decision = subscription_service.evaluate_access(_VERIFIED_IDENTITY)

    assert decision.allowed is False
    assert decision.reason_code == f"subscription_{status.value}"


def test_subscription_service_denies_missing_profile(
    subscription_service: SubscriptionAccessService,
) -> None:
    decision = subscription_service.evaluate_access(_VERIFIED_IDENTITY)

    assert decision.allowed is False
    assert decision.reason_code == "profile_not_found"


def test_subscription_service_denies_expired_datetime(
    subscription_engine: object,
    subscription_service: SubscriptionAccessService,
) -> None:
    _insert_profile(
        subscription_engine,
        status=AIAgentSubscriptionStatus.ACTIVE,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    decision = subscription_service.evaluate_access(_VERIFIED_IDENTITY)

    assert decision.allowed is False
    assert decision.reason_code == "subscription_expired"


def test_subscription_service_allows_future_expiration(
    subscription_engine: object,
    subscription_service: SubscriptionAccessService,
) -> None:
    _insert_profile(
        subscription_engine,
        status=AIAgentSubscriptionStatus.ACTIVE,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )

    decision = subscription_service.evaluate_access(_VERIFIED_IDENTITY)

    assert decision.allowed is True
