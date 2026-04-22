from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import cast

from sqlalchemy import func, select

from app.core.auth import VerifiedIdentity
from app.core.config import get_settings
from app.services.canonical_identity import get_canonical_identity_resolver
from app.smartrest.models import (
    CanonicalSourceMap,
    Profile,
    SourceSystem,
    User,
    get_sync_session_factory,
)


class PlatformAdminServiceError(RuntimeError):
    pass


class PlatformAdminTargetNotFoundError(PlatformAdminServiceError):
    pass


class PlatformAdminTargetValidationError(PlatformAdminServiceError):
    pass


@dataclass(frozen=True)
class PlatformAdminProfileSummary:
    profile_id: int
    name: str | None
    profile_nick: str | None
    subscription_status: str
    subscription_expires_at: datetime | None
    default_user_id: int | None
    user_count: int


class PlatformAdminService:
    def __init__(self) -> None:
        self._session_factory = get_sync_session_factory()

    def list_profiles(self) -> list[PlatformAdminProfileSummary]:
        settings = get_settings()
        with self._session_factory() as session:
            profiles = session.scalars(select(Profile).order_by(Profile.id)).all()
            user_stats = {
                int(profile_id): (
                    int(user_count),
                    int(default_user_id) if default_user_id else None,
                )
                for profile_id, user_count, default_user_id in session.execute(
                    select(
                        User.profile_id,
                        func.count(User.id),
                        func.min(User.id),
                    )
                    .where(User.deleted.is_not(True))
                    .group_by(User.profile_id)
                )
            }

            source_system_id = session.scalar(
                select(SourceSystem.id).where(
                    SourceSystem.server_name == settings.sync_source_system_server_name,
                    SourceSystem.cloud_num == settings.sync_source_system_cloud_num,
                    SourceSystem.status.in_(("active", "readonly")),
                )
            )
            canonical_defaults: dict[int, int] = {}
            if source_system_id is not None:
                canonical_defaults = {
                    int(profile_id): int(default_user_id)
                    for profile_id, default_user_id in session.execute(
                        select(
                            CanonicalSourceMap.profile_id,
                            func.min(CanonicalSourceMap.user_id),
                        )
                        .where(CanonicalSourceMap.source_system_id == int(source_system_id))
                        .group_by(CanonicalSourceMap.profile_id)
                    )
                }

            summaries: list[PlatformAdminProfileSummary] = []
            for profile in profiles:
                user_count, fallback_user_id = user_stats.get(int(profile.id), (0, None))
                summaries.append(
                    PlatformAdminProfileSummary(
                        profile_id=int(profile.id),
                        name=cast(str | None, profile.name),
                        profile_nick=cast(str | None, profile.profile_nick),
                        subscription_status=cast(
                            str,
                            profile.ai_agent_subscription_status,
                        ),
                        subscription_expires_at=cast(
                            datetime | None,
                            profile.ai_agent_subscription_expires_at,
                        ),
                        default_user_id=canonical_defaults.get(int(profile.id), fallback_user_id),
                        user_count=user_count,
                    )
                )
            return summaries

    def resolve_target(
        self,
        *,
        target_profile_id: int,
        target_profile_nick: str | None = None,
        target_user_id: int | None = None,
    ) -> VerifiedIdentity:
        settings = get_settings()
        resolver = get_canonical_identity_resolver()

        with self._session_factory() as session:
            profile = session.get(Profile, target_profile_id)
            if profile is None:
                raise PlatformAdminTargetNotFoundError("Target profile was not found.")

            resolved_profile_nick = cast(str | None, profile.profile_nick) or target_profile_nick
            if not resolved_profile_nick:
                raise PlatformAdminTargetValidationError(
                    "Target profile does not have a usable profile_nick."
                )
            if target_profile_nick and target_profile_nick != resolved_profile_nick:
                raise PlatformAdminTargetValidationError(
                    "target_profile_nick does not match the selected profile."
                )

            candidate_user_ids: list[int]
            if target_user_id is not None:
                user = session.scalar(
                    select(User).where(
                        User.id == target_user_id,
                        User.profile_id == target_profile_id,
                        User.deleted.is_not(True),
                    )
                )
                if user is None:
                    raise PlatformAdminTargetValidationError(
                        "target_user_id was not found under the selected profile."
                    )
                candidate_user_ids = [int(target_user_id)]
            else:
                candidate_user_ids = [
                    int(user_id)
                    for user_id in session.scalars(
                        select(User.id)
                        .where(
                            User.profile_id == target_profile_id,
                            User.deleted.is_not(True),
                        )
                        .order_by(User.id)
                    )
                ]

            for candidate_user_id in candidate_user_ids:
                resolution = resolver.resolve(
                    user_id=candidate_user_id,
                    profile_id=target_profile_id,
                    profile_nick=resolved_profile_nick,
                    source_server_name=settings.sync_source_system_server_name,
                    source_cloud_num=settings.sync_source_system_cloud_num,
                )
                if resolution is not None:
                    return VerifiedIdentity(
                        profile_nick=resolved_profile_nick,
                        user_id=candidate_user_id,
                        profile_id=target_profile_id,
                    )

            if target_user_id is not None:
                raise PlatformAdminTargetValidationError(
                    "target_user_id could not be resolved into canonical identity."
                )
            raise PlatformAdminTargetValidationError(
                "No resolvable user was found under the selected profile."
            )


@lru_cache(maxsize=1)
def get_platform_admin_service() -> PlatformAdminService:
    return PlatformAdminService()
