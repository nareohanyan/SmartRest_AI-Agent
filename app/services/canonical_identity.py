from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.smartrest.models import (
    CanonicalProfile,
    CanonicalSourceMap,
    CanonicalUser,
    Profile,
    ProfileSourceMap,
    SourceSystem,
    get_sync_session_factory,
)


@dataclass(frozen=True)
class CanonicalIdentityResolution:
    source_system_id: int
    canonical_profile_id: int
    canonical_user_id: int


class CanonicalIdentityResolver:
    def __init__(self) -> None:
        self._session_factory = get_sync_session_factory()

    def resolve(
        self,
        *,
        user_id: int,
        profile_id: int,
        profile_nick: str,
        source_server_name: str,
        source_cloud_num: int,
    ) -> CanonicalIdentityResolution | None:
        with self._session_factory() as session:
            source_system = session.scalar(
                select(SourceSystem).where(
                    SourceSystem.server_name == source_server_name,
                    SourceSystem.cloud_num == source_cloud_num,
                    SourceSystem.status.in_(("active", "readonly")),
                )
            )
            if source_system is None:
                return None

            canonical_profile_id = self._resolve_canonical_profile_id(
                session=session,
                source_system_id=int(source_system.id),
                profile_id=profile_id,
                profile_nick=profile_nick,
            )
            if canonical_profile_id is None:
                return None

            canonical_user_id = self._resolve_canonical_user_id(
                session=session,
                source_system_id=int(source_system.id),
                canonical_profile_id=canonical_profile_id,
                profile_id=profile_id,
                user_id=user_id,
            )
            if canonical_user_id is None:
                return None

            return CanonicalIdentityResolution(
                source_system_id=int(source_system.id),
                canonical_profile_id=canonical_profile_id,
                canonical_user_id=canonical_user_id,
            )

    def _resolve_canonical_profile_id(
        self,
        *,
        session: Session,
        source_system_id: int,
        profile_id: int,
        profile_nick: str,
    ) -> int | None:
        profile_map = session.scalar(
            select(ProfileSourceMap).where(
                ProfileSourceMap.source_system_id == source_system_id,
                ProfileSourceMap.profile_id == profile_id,
            )
        )
        if profile_map is not None:
            return int(profile_map.canonical_profile_id)

        canonical_profile = session.scalar(
            select(CanonicalProfile).where(
                CanonicalProfile.source_system_id == source_system_id,
                CanonicalProfile.profile_id == profile_id,
            )
        )
        if canonical_profile is not None:
            return int(canonical_profile.id)

        if profile_nick:
            canonical_profile_by_nick = session.scalar(
                select(CanonicalProfile).where(CanonicalProfile.profile_nick == profile_nick)
            )
            if canonical_profile_by_nick is not None:
                return int(canonical_profile_by_nick.id)

        # Fallback for non-synced legacy profiles in SmartRest.
        legacy_profile = session.get(Profile, profile_id)
        if legacy_profile is None:
            return None
        return int(profile_id)

    def _resolve_canonical_user_id(
        self,
        *,
        session: Session,
        source_system_id: int,
        canonical_profile_id: int,
        profile_id: int,
        user_id: int,
    ) -> int | None:
        canonical_source = session.scalar(
            select(CanonicalSourceMap).where(
                CanonicalSourceMap.source_system_id == source_system_id,
                CanonicalSourceMap.profile_id == profile_id,
                CanonicalSourceMap.user_id == user_id,
            )
        )
        if canonical_source is not None:
            return int(canonical_source.canonical_user_id)

        canonical_user = session.scalar(
            select(CanonicalUser).where(
                CanonicalUser.canonical_profile_id == canonical_profile_id,
                CanonicalUser.user_id == user_id,
            )
        )
        if canonical_user is not None:
            return int(canonical_user.id)
        return None


@lru_cache(maxsize=1)
def get_canonical_identity_resolver() -> CanonicalIdentityResolver:
    return CanonicalIdentityResolver()

