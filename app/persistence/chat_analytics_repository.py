from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID

from sqlalchemy.orm import Session

from app.chat_analytics.models import AgentRun, Chat, ChatMetadata, Message
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

    def get_or_create_chat(
        self,
        *,
        chat_id: UUID,
        user_id: int | str,
        profile_id: int | str,
        profile_nick: str,
        title: str | None = None,
        metadata_json: dict[str, object] | None = None,
    ) -> Chat:
        if not profile_nick.strip():
            raise PersistenceValidationError("profile_nick must be non-empty.")

        chat = self._session.get(Chat, chat_id)
        if chat is not None:
            return chat

        chat = Chat(
            id=chat_id,
            user_id=_coerce_bigint(user_id, field_name="user_id"),
            profile_id=_coerce_bigint(profile_id, field_name="profile_id"),
            profile_nick=profile_nick.strip(),
            title=title,
        )
        self._session.add(chat)
        self._session.flush()
        if metadata_json:
            for key, value in metadata_json.items():
                metadata_entry = ChatMetadata(
                    chat_id=cast(UUID, chat.id),
                    key=key,
                    value_json=value,
                )
                self._session.add(metadata_entry)
            self._session.flush()
        return chat

    def create_run_started(
        self,
        *,
        chat_id: UUID,
        user_id: int | str,
        profile_id: int | str,
        profile_nick: str,
        intent: str | None = None,
    ) -> AgentRun:
        if not profile_nick.strip():
            raise PersistenceValidationError("profile_nick must be non-empty.")

        chat = self._session.get(Chat, chat_id)
        if chat is None:
            raise PersistenceNotFoundError(f"Chat not found: {chat_id}")

        run = AgentRun(
            chat_id=chat_id,
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
        chat_id: UUID,
        run_id: UUID,
        question_text: str,
        answer_text: str | None = None,
        status: RunStatus = RunStatus.COMPLETED,
        error_message: str | None = None,
        error_code: str | None = None,
    ) -> Message:
        if not question_text.strip():
            raise PersistenceValidationError("question_text must be non-empty.")

        chat = self._session.get(Chat, chat_id)
        if chat is None:
            raise PersistenceNotFoundError(f"Chat not found: {chat_id}")

        run = self._session.get(AgentRun, run_id)
        if run is None:
            raise PersistenceNotFoundError(f"Run not found: {run_id}")

        message = Message(
            chat_id=chat_id,
            run_id=run_id,
            question_text=question_text.strip(),
            answer_text=answer_text,
            status=_map_runtime_status_to_message_status(status),
            clarification_needed=status is RunStatus.CLARIFY,
            error_message=error_message,
            error_code=error_code,
        )
        self._session.add(message)
        chat_obj = cast(Any, chat)
        chat_obj.last_message_at = datetime.now(timezone.utc)
        self._session.flush()
        return message


def _map_runtime_status_to_message_status(status: RunStatus) -> str:
    if status is RunStatus.COMPLETED:
        return "completed"
    if status is RunStatus.ONBOARDING:
        return "onboarding"
    if status is RunStatus.CLARIFY:
        return "clarify"
    if status is RunStatus.REJECTED:
        return "rejected"
    if status is RunStatus.DENIED:
        return "denied"
    if status is RunStatus.FAILED:
        return "failed"
    raise PersistenceValidationError(f"Unsupported message status: {status.value}")
