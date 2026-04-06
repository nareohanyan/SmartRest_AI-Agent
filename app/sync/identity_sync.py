from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.source import get_toon_lahmajo_engine
from app.smartrest.models import (
    CanonicalProfile,
    CanonicalSourceMap,
    CanonicalUser,
    ProfileSourceMap,
    SourceSystem,
    SyncError,
    SyncRun,
    SyncState,
    get_sync_session_factory,
)

_STREAM_PROFILES = "profiles"
_STREAM_USERS = "profiles_users"


@dataclass(frozen=True)
class SyncRunSummary:
    run_id: int
    status: str
    profiles_processed: int
    users_processed: int
    errors_count: int


class ToonLahmajoIdentitySync:
    def __init__(
        self,
        *,
        target_session_factory: sessionmaker[Session] | None = None,
        source_engine: Engine | None = None,
    ) -> None:
        self._target_session_factory = target_session_factory or get_sync_session_factory()
        self._source_engine = source_engine or get_toon_lahmajo_engine()

    def run(
        self,
        *,
        server_name: str | None = None,
        cloud_num: int | None = None,
        batch_size_profiles: int | None = None,
        batch_size_users: int | None = None,
    ) -> SyncRunSummary:
        settings = get_settings()
        source_server_name = (server_name or settings.sync_source_system_server_name).strip()
        source_cloud_num = (
            cloud_num
            if cloud_num is not None
            else settings.sync_source_system_cloud_num
        )
        profiles_batch_size = batch_size_profiles or settings.sync_batch_size_profiles
        users_batch_size = batch_size_users or settings.sync_batch_size_users

        with self._target_session_factory() as session:
            source_system_id = _ensure_source_system(
                session=session,
                server_name=source_server_name,
                cloud_num=source_cloud_num,
            )
            sync_run = SyncRun(
                source_system_id=source_system_id,
                status="running",
                profiles_processed=0,
                users_processed=0,
                errors_count=0,
            )
            session.add(sync_run)
            session.commit()
            session.refresh(sync_run)
            sync_run_id = cast(int, sync_run.id)

            try:
                with self._source_engine.connect() as source_conn:
                    profiles_processed, profile_errors = _sync_profiles_stream(
                        source_conn=source_conn,
                        session=session,
                        sync_run_id=sync_run_id,
                        source_system_id=source_system_id,
                        batch_size=profiles_batch_size,
                    )
                    users_processed, user_errors = _sync_users_stream(
                        source_conn=source_conn,
                        session=session,
                        sync_run_id=sync_run_id,
                        source_system_id=source_system_id,
                        batch_size=users_batch_size,
                    )
            except Exception as exc:
                session.execute(
                    update(SyncRun)
                    .where(SyncRun.id == sync_run_id)
                    .values(
                        status="failed",
                        finished_at=datetime.now(timezone.utc),
                        details={"fatal_error": str(exc)},
                    )
                )
                session.commit()
                raise

            total_errors = profile_errors + user_errors
            final_status = "success" if total_errors == 0 else "partial"
            session.execute(
                update(SyncRun)
                .where(SyncRun.id == sync_run_id)
                .values(
                    status=final_status,
                    finished_at=datetime.now(timezone.utc),
                    profiles_processed=profiles_processed,
                    users_processed=users_processed,
                    errors_count=total_errors,
                    details={
                        "source_system": source_server_name,
                        "cloud_num": source_cloud_num,
                        "streams": [_STREAM_PROFILES, _STREAM_USERS],
                    },
                )
            )
            session.commit()

            return SyncRunSummary(
                run_id=sync_run_id,
                status=final_status,
                profiles_processed=profiles_processed,
                users_processed=users_processed,
                errors_count=total_errors,
            )


def _ensure_source_system(
    *,
    session: Session,
    server_name: str,
    cloud_num: int,
) -> int:
    existing = session.scalar(
        select(SourceSystem).where(
            SourceSystem.server_name == server_name,
            SourceSystem.cloud_num == cloud_num,
        )
    )
    if existing is not None:
        return int(existing.id)

    source_system = SourceSystem(
        server_name=server_name,
        cloud_num=cloud_num,
        status="active",
    )
    session.add(source_system)
    session.commit()
    session.refresh(source_system)
    return int(source_system.id)


def _stream_cursor(
    *,
    session: Session,
    source_system_id: int,
    stream_name: str,
) -> int:
    state = session.scalar(
        select(SyncState).where(
            SyncState.source_system_id == source_system_id,
            SyncState.stream_name == stream_name,
        )
    )
    if state is None or state.last_cursor is None:
        return 0
    return int(state.last_cursor)


def _upsert_stream_state(
    *,
    session: Session,
    source_system_id: int,
    stream_name: str,
    last_cursor: int,
) -> None:
    stmt = pg_insert(SyncState).values(
        source_system_id=source_system_id,
        stream_name=stream_name,
        last_cursor=last_cursor,
        last_synced_at=datetime.now(timezone.utc),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[SyncState.source_system_id, SyncState.stream_name],
        set_={
            "last_cursor": last_cursor,
            "last_synced_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        },
    )
    session.execute(stmt)


def _record_sync_error(
    *,
    session: Session,
    sync_run_id: int,
    source_system_id: int,
    stream_name: str,
    entity_key: str | None,
    error_code: str,
    error_message: str,
    payload_fragment: dict[str, Any] | None,
) -> None:
    session.add(
        SyncError(
            sync_run_id=sync_run_id,
            source_system_id=source_system_id,
            stream_name=stream_name,
            entity_key=entity_key,
            error_code=error_code,
            error_message=error_message,
            payload_fragment=payload_fragment,
        )
    )


def _sync_profiles_stream(
    *,
    source_conn: Connection,
    session: Session,
    sync_run_id: int,
    source_system_id: int,
    batch_size: int,
) -> tuple[int, int]:
    processed = 0
    errors = 0
    cursor = _stream_cursor(
        session=session,
        source_system_id=source_system_id,
        stream_name=_STREAM_PROFILES,
    )

    while True:
        rows = source_conn.execute(
            text(
                """
                SELECT id, nic
                FROM profiles
                WHERE id > :cursor
                ORDER BY id
                LIMIT :batch_size
                """
            ),
            {"cursor": cursor, "batch_size": batch_size},
        ).mappings().all()
        if not rows:
            break

        for row in rows:
            profile_id = int(row["id"])
            profile_nick_value = row.get("nic") or f"profile_{profile_id}"
            profile_nick = profile_nick_value.strip() or f"profile_{profile_id}"
            try:
                with session.begin_nested():
                    canonical_profile_id = _upsert_canonical_profile(
                        session=session,
                        source_system_id=source_system_id,
                        profile_id=profile_id,
                        profile_nick=profile_nick,
                    )
                    _upsert_profile_source_map(
                        session=session,
                        source_system_id=source_system_id,
                        profile_id=profile_id,
                        canonical_profile_id=canonical_profile_id,
                    )
                processed += 1
                cursor = profile_id
            except Exception as exc:
                errors += 1
                _record_sync_error(
                    session=session,
                    sync_run_id=sync_run_id,
                    source_system_id=source_system_id,
                    stream_name=_STREAM_PROFILES,
                    entity_key=str(profile_id),
                    error_code="profile_upsert_failed",
                    error_message=str(exc),
                    payload_fragment={"profile_id": profile_id, "profile_nick": profile_nick},
                )

        _upsert_stream_state(
            session=session,
            source_system_id=source_system_id,
            stream_name=_STREAM_PROFILES,
            last_cursor=cursor,
        )
        session.commit()

    return processed, errors


def _sync_users_stream(
    *,
    source_conn: Connection,
    session: Session,
    sync_run_id: int,
    source_system_id: int,
    batch_size: int,
) -> tuple[int, int]:
    processed = 0
    errors = 0
    cursor = _stream_cursor(
        session=session,
        source_system_id=source_system_id,
        stream_name=_STREAM_USERS,
    )

    while True:
        rows = source_conn.execute(
            text(
                """
                SELECT id, profile_id, username
                FROM profiles_users
                WHERE id > :cursor
                ORDER BY id
                LIMIT :batch_size
                """
            ),
            {"cursor": cursor, "batch_size": batch_size},
        ).mappings().all()
        if not rows:
            break

        for row in rows:
            user_id = int(row["id"])
            profile_id = int(row["profile_id"])
            username = row.get("username")
            try:
                with session.begin_nested():
                    canonical_profile_id = _resolve_canonical_profile_id(
                        session=session,
                        source_system_id=source_system_id,
                        profile_id=profile_id,
                    )
                    if canonical_profile_id is None:
                        raise ValueError("canonical_profile_missing")

                    canonical_user_id = _upsert_canonical_user(
                        session=session,
                        canonical_profile_id=canonical_profile_id,
                        user_id=user_id,
                        username=username,
                    )
                    _upsert_canonical_source_map(
                        session=session,
                        source_system_id=source_system_id,
                        profile_id=profile_id,
                        user_id=user_id,
                        canonical_user_id=canonical_user_id,
                    )
                processed += 1
                cursor = user_id
            except Exception as exc:
                errors += 1
                _record_sync_error(
                    session=session,
                    sync_run_id=sync_run_id,
                    source_system_id=source_system_id,
                    stream_name=_STREAM_USERS,
                    entity_key=f"profile:{profile_id}:user:{user_id}",
                    error_code="user_upsert_failed",
                    error_message=str(exc),
                    payload_fragment={"profile_id": profile_id, "user_id": user_id},
                )

        _upsert_stream_state(
            session=session,
            source_system_id=source_system_id,
            stream_name=_STREAM_USERS,
            last_cursor=cursor,
        )
        session.commit()

    return processed, errors


def _upsert_canonical_profile(
    *,
    session: Session,
    source_system_id: int,
    profile_id: int,
    profile_nick: str,
) -> int:
    stmt = (
        pg_insert(CanonicalProfile)
        .values(
            source_system_id=source_system_id,
            profile_id=profile_id,
            profile_nick=profile_nick,
            status="active",
        )
        .on_conflict_do_update(
            index_elements=[CanonicalProfile.source_system_id, CanonicalProfile.profile_id],
            set_={
                "profile_nick": profile_nick,
                "status": "active",
                "updated_at": datetime.now(timezone.utc),
            },
        )
        .returning(CanonicalProfile.id)
    )
    return int(session.execute(stmt).scalar_one())


def _upsert_profile_source_map(
    *,
    session: Session,
    source_system_id: int,
    profile_id: int,
    canonical_profile_id: int,
) -> None:
    stmt = pg_insert(ProfileSourceMap).values(
        source_system_id=source_system_id,
        canonical_profile_id=canonical_profile_id,
        profile_id=profile_id,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[ProfileSourceMap.source_system_id, ProfileSourceMap.profile_id],
        set_={
            "canonical_profile_id": canonical_profile_id,
            "updated_at": datetime.now(timezone.utc),
        },
    )
    session.execute(stmt)


def _resolve_canonical_profile_id(
    *,
    session: Session,
    source_system_id: int,
    profile_id: int,
) -> int | None:
    mapped = session.scalar(
        select(ProfileSourceMap.canonical_profile_id).where(
            ProfileSourceMap.source_system_id == source_system_id,
            ProfileSourceMap.profile_id == profile_id,
        )
    )
    if mapped is not None:
        return int(mapped)

    canonical_profile = session.scalar(
        select(CanonicalProfile).where(
            CanonicalProfile.source_system_id == source_system_id,
            CanonicalProfile.profile_id == profile_id,
        )
    )
    if canonical_profile is None:
        return None
    return int(canonical_profile.id)


def _upsert_canonical_user(
    *,
    session: Session,
    canonical_profile_id: int,
    user_id: int,
    username: str | None,
) -> int:
    stmt = (
        pg_insert(CanonicalUser)
        .values(
            canonical_profile_id=canonical_profile_id,
            user_id=user_id,
            username=username,
            status="active",
        )
        .on_conflict_do_update(
            index_elements=[CanonicalUser.canonical_profile_id, CanonicalUser.user_id],
            set_={
                "username": username,
                "status": "active",
                "updated_at": datetime.now(timezone.utc),
            },
        )
        .returning(CanonicalUser.id)
    )
    return int(session.execute(stmt).scalar_one())


def _upsert_canonical_source_map(
    *,
    session: Session,
    source_system_id: int,
    profile_id: int,
    user_id: int,
    canonical_user_id: int,
) -> None:
    stmt = pg_insert(CanonicalSourceMap).values(
        source_system_id=source_system_id,
        canonical_user_id=canonical_user_id,
        profile_id=profile_id,
        user_id=user_id,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            CanonicalSourceMap.source_system_id,
            CanonicalSourceMap.profile_id,
            CanonicalSourceMap.user_id,
        ],
        set_={
            "canonical_user_id": canonical_user_id,
            "updated_at": datetime.now(timezone.utc),
        },
    )
    session.execute(stmt)


def run_toon_lahmajo_identity_sync(
    *,
    server_name: str | None = None,
    cloud_num: int | None = None,
    batch_size_profiles: int | None = None,
    batch_size_users: int | None = None,
) -> SyncRunSummary:
    return ToonLahmajoIdentitySync().run(
        server_name=server_name,
        cloud_num=cloud_num,
        batch_size_profiles=batch_size_profiles,
        batch_size_users=batch_size_users,
    )
