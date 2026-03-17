from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, cast
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.analytics import get_chat_analytics_session_factory
from app.persistence.chat_analytics_repository import ChatAnalyticsRepository
from app.persistence.errors import PersistenceNotFoundError, PersistenceValidationError
from app.persistence.thread_id_mapper import to_internal_thread_uuid
from app.schemas.agent import RunStatus

PERSISTENCE_WARNING_INVALID_THREAD_ID = "persistence_invalid_thread_id"
PERSISTENCE_WARNING_INVALID_IDENTITY = "persistence_invalid_identity"
PERSISTENCE_WARNING_INVALID_INPUT = "persistence_invalid_input"
PERSISTENCE_WARNING_NOT_FOUND = "persistence_not_found"
PERSISTENCE_WARNING_MISSING_CONTEXT = "persistence_missing_context"
PERSISTENCE_WARNING_UNAVAILABLE = "persistence_unavailable"


@dataclass(frozen=True)
class StartRunPersistenceResult:
    internal_thread_id: UUID | None = None
    internal_run_id: UUID | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FinishRunPersistenceResult:
    warnings: list[str] = field(default_factory=list)


class RuntimePersistenceService:
    """Orchestrates runtime persistence with fail-soft behavior."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] | None = None,
        repository_factory: Callable[[Session], ChatAnalyticsRepository] = ChatAnalyticsRepository,
    ) -> None:
        self._session_factory = session_factory
        self._repository_factory = repository_factory

    def _open_session(self) -> Session:
        if self._session_factory is not None:
            return self._session_factory()

        return get_chat_analytics_session_factory()()

    @staticmethod
    def _is_integer_like(value: int | str) -> bool:
        if isinstance(value, int):
            return True

        value_str = value.strip()
        if not value_str:
            return False

        try:
            int(value_str)
        except ValueError:
            return False
        return True

    def start_run(
        self,
        *,
        external_thread_id: str,
        user_id: int | str,
        profile_id: int | str,
        profile_nick: str,
        intent: str | None = None,
        title: str | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> StartRunPersistenceResult:
        try:
            internal_thread_id = to_internal_thread_uuid(external_thread_id)
        except PersistenceValidationError:
            return StartRunPersistenceResult(
                warnings=[PERSISTENCE_WARNING_INVALID_THREAD_ID],
            )

        if not self._is_integer_like(user_id) or not self._is_integer_like(profile_id):
            return StartRunPersistenceResult(warnings=[PERSISTENCE_WARNING_INVALID_IDENTITY])

        try:
            session = self._open_session()
        except Exception:
            return StartRunPersistenceResult(warnings=[PERSISTENCE_WARNING_UNAVAILABLE])
        try:
            repository = self._repository_factory(session)
            thread = repository.get_or_create_thread(
                thread_id=internal_thread_id,
                user_id=user_id,
                profile_id=profile_id,
                profile_nick=profile_nick,
                title=title,
                metadata_json=metadata_json,
            )
            run = repository.create_run_started(
                thread_id=cast(UUID, thread.id),
                user_id=user_id,
                profile_id=profile_id,
                profile_nick=profile_nick,
                intent=intent,
            )
            session.commit()
            return StartRunPersistenceResult(
                internal_thread_id=cast(UUID, thread.id),
                internal_run_id=cast(UUID, run.id),
            )
        except PersistenceValidationError:
            session.rollback()
            return StartRunPersistenceResult(warnings=[PERSISTENCE_WARNING_INVALID_IDENTITY])
        except Exception:
            session.rollback()
            return StartRunPersistenceResult(warnings=[PERSISTENCE_WARNING_UNAVAILABLE])
        finally:
            session.close()

    def finish_run(
        self,
        *,
        internal_thread_id: UUID | None,
        internal_run_id: UUID | None,
        status: RunStatus,
        question: str,
        answer: str | None,
        error_message: str | None = None,
        error_code: str | None = None,
    ) -> FinishRunPersistenceResult:
        if internal_thread_id is None or internal_run_id is None:
            return FinishRunPersistenceResult(warnings=[PERSISTENCE_WARNING_MISSING_CONTEXT])

        try:
            session = self._open_session()
        except Exception:
            return FinishRunPersistenceResult(warnings=[PERSISTENCE_WARNING_UNAVAILABLE])
        try:
            repository = self._repository_factory(session)
            repository.update_run_terminal_status(
                run_id=internal_run_id,
                status=status,
                error_message=error_message,
                error_code=error_code,
            )
            repository.write_message(
                thread_id=internal_thread_id,
                run_id=internal_run_id,
                question=question,
                answer=answer,
            )
            session.commit()
            return FinishRunPersistenceResult()
        except PersistenceValidationError:
            session.rollback()
            return FinishRunPersistenceResult(warnings=[PERSISTENCE_WARNING_INVALID_INPUT])
        except PersistenceNotFoundError:
            session.rollback()
            return FinishRunPersistenceResult(warnings=[PERSISTENCE_WARNING_NOT_FOUND])
        except Exception:
            session.rollback()
            return FinishRunPersistenceResult(warnings=[PERSISTENCE_WARNING_UNAVAILABLE])
        finally:
            session.close()


@lru_cache(maxsize=1)
def get_runtime_persistence_service() -> RuntimePersistenceService:
    return RuntimePersistenceService()
