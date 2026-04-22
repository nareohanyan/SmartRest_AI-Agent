from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.services.canonical_identity import CanonicalIdentityResolver
from app.smartrest.models import (
    CanonicalProfile,
    CanonicalSourceMap,
    CanonicalUser,
    Profile,
    ProfileSourceMap,
    SourceSystem,
)


@pytest.fixture
def resolver() -> Iterator[CanonicalIdentityResolver]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Profile.__table__.create(engine)
    SourceSystem.__table__.create(engine)
    CanonicalProfile.__table__.create(engine)
    CanonicalUser.__table__.create(engine)
    ProfileSourceMap.__table__.create(engine)
    CanonicalSourceMap.__table__.create(engine)

    resolver = CanonicalIdentityResolver()
    resolver._session_factory = lambda: Session(  # type: ignore[method-assign]
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    try:
        yield resolver
    finally:
        engine.dispose()


def test_resolver_finds_canonical_identity_from_maps(
    resolver: CanonicalIdentityResolver,
) -> None:
    with resolver._session_factory() as session:  # type: ignore[attr-defined]
        session.add(SourceSystem(id=1, server_name="toon_lahmajo", cloud_num=1, status="active"))
        session.add(
            CanonicalProfile(
                id=10,
                source_system_id=1,
                profile_id=201,
                profile_nick="nick",
                status="active",
            )
        )
        session.add(
            CanonicalUser(
                id=20,
                canonical_profile_id=10,
                user_id=101,
                username="user",
                status="active",
            )
        )
        session.add(
            ProfileSourceMap(
                id=30,
                source_system_id=1,
                canonical_profile_id=10,
                profile_id=201,
            )
        )
        session.add(
            CanonicalSourceMap(
                id=40,
                source_system_id=1,
                canonical_user_id=20,
                profile_id=201,
                user_id=101,
            )
        )
        session.commit()

    resolution = resolver.resolve(
        user_id=101,
        profile_id=201,
        profile_nick="nick",
        source_server_name="toon_lahmajo",
        source_cloud_num=1,
    )

    assert resolution is not None
    assert resolution.source_system_id == 1
    assert resolution.canonical_profile_id == 10
    assert resolution.canonical_user_id == 20


def test_resolver_returns_none_for_unknown_source_system(
    resolver: CanonicalIdentityResolver,
) -> None:
    resolution = resolver.resolve(
        user_id=101,
        profile_id=201,
        profile_nick="nick",
        source_server_name="unknown",
        source_cloud_num=1,
    )
    assert resolution is None
