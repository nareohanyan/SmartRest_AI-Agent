from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID

from sqlalchemy.orm import Session

from app.chat_analytics.models import AgentRun, Message, Thread
from app.persistence.errors import PersistenceNotFoundError, PersistenceValidationError
from app.persistence.status_mapper import map_runtime_status_to_db
from app.schemas.agent import RunStatus


def _coerce_bigint(value: int | str, *, field_name: str) -> int:
    if isinstance(value, int):
        return value

    value_str = value.strip()
    if not value_str:
        raise PersistenceValidationError(f"{field_name} must be a non-empty integer value.")

    try:
        return int(value_str)
    except ValueError as exc:
        raise PersistenceValidationError(f"{field_name} must be an integer.") from exc


class ChatAnalyticsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_or_create_thread(
        self,
        *,
        thread_id: UUID,
        user_id: int | str,
        profile_id: int | str,
        profile_nick: str,
        title: str | None = None,
        metadata_json: dict[str, object] | None = None,
    ) -> Thread:
        if not profile_nick.strip():
            raise PersistenceValidationError("profile_nick must be non-empty.")

        thread = self._session.get(Thread, thread_id)
        if thread is not None:
            return thread

        thread = Thread(
            id=thread_id,
            user_id=_coerce_bigint(user_id, field_name="user_id"),
            profile_id=_coerce_bigint(profile_id, field_name="profile_id"),
            profile_nick=profile_nick.strip(),
            title=title,
            metadata_json=metadata_json,
        )
        self._session.add(thread)
        self._session.flush()
        return thread

    def create_run_started(
        self,
        *,
        thread_id: UUID,
        user_id: int | str,
        profile_id: int | str,
        profile_nick: str,
        intent: str | None = None,
    ) -> AgentRun:
        if not profile_nick.strip():
            raise PersistenceValidationError("profile_nick must be non-empty.")

        thread = self._session.get(Thread, thread_id)
        if thread is None:
            raise PersistenceNotFoundError(f"Thread not found: {thread_id}")

        run = AgentRun(
            thread_id=thread_id,
            user_id=_coerce_bigint(user_id, field_name="user_id"),
            profile_id=_coerce_bigint(profile_id, field_name="profile_id"),
            profile_nick=profile_nick.strip(),
            intent=intent,
            status="started",
        )
        self._session.add(run)
        self._session.flush()
        return run

    def update_run_terminal_status(
        self,
        *,
        run_id: UUID,
        status: RunStatus,
        error_message: str | None = None,
        error_code: str | None = None,
    ) -> AgentRun:
        if status is RunStatus.RUNNING:
            raise PersistenceValidationError("Terminal status update cannot use 'running'.")

        run = self._session.get(AgentRun, run_id)
        if run is None:
            raise PersistenceNotFoundError(f"Run not found: {run_id}")

        mapped_status, mapped_error_code = map_runtime_status_to_db(status)
        run_obj = cast(Any, run)
        run_obj.status = mapped_status
        run_obj.error_message = error_message
        run_obj.error_code = error_code or mapped_error_code
        self._session.flush()
        return run

    def write_message(
        self,
        *,
        thread_id: UUID,
        run_id: UUID,
        question: str,
        answer: str | None = None,
    ) -> Message:
        if not question.strip():
            raise PersistenceValidationError("question must be non-empty.")

        thread = self._session.get(Thread, thread_id)
        if thread is None:
            raise PersistenceNotFoundError(f"Thread not found: {thread_id}")

        run = self._session.get(AgentRun, run_id)
        if run is None:
            raise PersistenceNotFoundError(f"Run not found: {run_id}")

        message = Message(
            thread_id=thread_id,
            run_id=run_id,
            question=question.strip(),
            answer=answer,
        )
        self._session.add(message)
        thread_obj = cast(Any, thread)
        thread_obj.last_message_at = datetime.now(timezone.utc)
        self._session.flush()
        return message
