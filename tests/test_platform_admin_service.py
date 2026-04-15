from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.services.platform_admin import (
    PlatformAdminService,
    PlatformAdminTargetNotFoundError,
    PlatformAdminTargetValidationError,
)
from app.smartrest.models import (
    Base,
    CanonicalProfile,
    CanonicalSourceMap,
    CanonicalUser,
    Profile,
    ProfileSourceMap,
    SourceSystem,
    User,
)


@pytest.fixture
def platform_admin_engine() -> Iterator[object]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    tables = [
        SourceSystem.__table__,
        Profile.__table__,
        User.__table__,
        CanonicalProfile.__table__,
        ProfileSourceMap.__table__,
        CanonicalUser.__table__,
        CanonicalSourceMap.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def platform_admin_service(
    platform_admin_engine: object,
    monkeypatch: pytest.MonkeyPatch,
) -> PlatformAdminService:
    monkeypatch.setattr(
        "app.services.platform_admin.get_sync_session_factory",
        lambda: lambda: Session(bind=platform_admin_engine),
    )
    monkeypatch.setenv("SMARTREST_SYNC_SOURCE_SYSTEM_SERVER_NAME", "toon_lahmajo")
    monkeypatch.setenv("SMARTREST_SYNC_SOURCE_SYSTEM_CLOUD_NUM", "1")
    monkeypatch.setattr(
        "app.services.platform_admin.get_canonical_identity_resolver",
        lambda: type(
            "_Resolver",
            (),
            {
                "resolve": staticmethod(
                    lambda **kwargs: None
                    if kwargs.get("user_id") == 201
                    else type(
                        "_Resolution",
                        (),
                        {
                            "source_system_id": 1,
                            "canonical_profile_id": 98,
                            "canonical_user_id": 1001,
                        },
                    )()
                )
            },
        )(),
    )
    return PlatformAdminService()


def _seed_identity_graph(platform_admin_engine: object) -> None:
    with Session(bind=platform_admin_engine) as session:
        session.add(
            SourceSystem(
                id=1,
                server_name="toon_lahmajo",
                cloud_num=1,
                status="active",
            )
        )
        session.add(
            Profile(
                id=98,
                name="Tun Lahmajo",
                profile_nick="tunlahmajo_1681123576",
                ai_agent_subscription_status="expired",
            )
        )
        session.add(Profile(id=376, name="Empty", profile_nick="empty_profile"))
        session.add_all(
            [
                User(id=101, profile_id=98, username="owner", deleted=False),
                User(id=102, profile_id=98, username="manager", deleted=False),
                User(id=201, profile_id=376, username="ghost", deleted=False),
            ]
        )
        session.add(
            CanonicalProfile(
                id=98,
                source_system_id=1,
                profile_id=98,
                profile_nick="tunlahmajo_1681123576",
            )
        )
        session.add(
            ProfileSourceMap(
                id=1,
                source_system_id=1,
                profile_id=98,
                canonical_profile_id=98,
            )
        )
        session.add(CanonicalUser(id=1001, canonical_profile_id=98, user_id=101))
        session.add(
            CanonicalSourceMap(
                id=1,
                source_system_id=1,
                profile_id=98,
                user_id=101,
                canonical_user_id=1001,
            )
        )
        session.commit()


def test_list_profiles_returns_default_user_ids(
    platform_admin_engine: object,
    platform_admin_service: PlatformAdminService,
) -> None:
    _seed_identity_graph(platform_admin_engine)

    profiles = platform_admin_service.list_profiles()

    assert [profile.profile_id for profile in profiles] == [98, 376]
    assert profiles[0].default_user_id == 101
    assert profiles[0].user_count == 2


def test_resolve_target_returns_resolvable_identity(
    platform_admin_engine: object,
    platform_admin_service: PlatformAdminService,
) -> None:
    _seed_identity_graph(platform_admin_engine)

    identity = platform_admin_service.resolve_target(target_profile_id=98)

    assert identity.profile_id == 98
    assert identity.profile_nick == "tunlahmajo_1681123576"
    assert identity.user_id == 101


def test_resolve_target_rejects_missing_profile(
    platform_admin_service: PlatformAdminService,
) -> None:
    with pytest.raises(PlatformAdminTargetNotFoundError):
        platform_admin_service.resolve_target(target_profile_id=999)


def test_resolve_target_rejects_profile_nick_mismatch(
    platform_admin_engine: object,
    platform_admin_service: PlatformAdminService,
) -> None:
    _seed_identity_graph(platform_admin_engine)

    with pytest.raises(PlatformAdminTargetValidationError):
        platform_admin_service.resolve_target(
            target_profile_id=98,
            target_profile_nick="other",
        )
