from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, delete, select, text
from sqlalchemy.orm import Session

from app.api.schemas import AgentRunRequest
from app.chat_analytics.models import AgentRun, Base, Chat, ChatEvent, Feedback, Message
from app.core.auth import VerifiedIdentity
from app.persistence.runtime_persistence import RuntimePersistenceService
from app.schemas.agent import RunStatus
from app.services.agent_runtime import AgentRuntimeExecutionError, AgentRuntimeService

_VERIFIED_IDENTITY = VerifiedIdentity(profile_nick="nick", user_id=101, profile_id=201)


def _chat_analytics_database_url() -> str:
    db_url = os.getenv("SMARTREST_CHAT_ANALYTICS_DATABASE_URL") or os.getenv(
        "CHAT_ANALYTICS_DATABASE_URL"
    )
    if not db_url:
        pytest.skip("CHAT_ANALYTICS_DATABASE_URL is not set; skipping DB integration tests.")
    return db_url


def _schema_scoped_database_url(base_url: str, schema_name: str) -> str:
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}options=-csearch_path={schema_name}"


@pytest.fixture(scope="session")
def analytics_engine() -> Iterator[Engine]:
    base_db_url = _chat_analytics_database_url()
    schema_name = f"test_runtime_{uuid4().hex}"
    base_engine = create_engine(base_db_url, future=True)
    engine = create_engine(_schema_scoped_database_url(base_db_url, schema_name), future=True)
    try:
        with base_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Chat analytics DB is not reachable: {exc}")

    Base.metadata.create_all(engine)
    yield engine
    with base_engine.begin() as connection:
        connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
    engine.dispose()
    base_engine.dispose()


@pytest.fixture
def persistence_service(analytics_engine: Engine) -> RuntimePersistenceService:
    def _session_factory() -> Session:
        return Session(
            bind=analytics_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    return RuntimePersistenceService(session_factory=_session_factory)


def _request_payload(chat_id: UUID) -> AgentRunRequest:
    return AgentRunRequest.model_validate(
        {
            "chat_id": str(chat_id),
            "user_question": "What were total sales 2026-03-01 to 2026-03-07?",
            "auth": {
                "profile_nick": "nick",
                "user_id": 101,
                "profile_id": 201,
                "current_timestamp": 0,
                "token": "0" * 64,
            },
            "scope_request": {
                "user_id": 101,
                "profile_id": 201,
                "profile_nick": "nick",
                "metadata": {},
            },
        }
    )


def _cleanup_chat_records(engine: Engine, chat_id: UUID) -> None:
    with Session(bind=engine) as session:
        session.execute(delete(Feedback).where(Feedback.chat_id == chat_id))
        session.execute(delete(Message).where(Message.chat_id == chat_id))
        session.execute(delete(AgentRun).where(AgentRun.chat_id == chat_id))
        session.execute(delete(ChatEvent).where(ChatEvent.chat_id == chat_id))
        session.execute(delete(Chat).where(Chat.id == chat_id))
        session.commit()


class _TerminalGraph:
    def __init__(
        self,
        *,
        status: RunStatus,
        final_answer: str,
        needs_clarification: bool = False,
        clarification_question: str | None = None,
    ) -> None:
        self._status = status
        self._final_answer = final_answer
        self._needs_clarification = needs_clarification
        self._clarification_question = clarification_question

    def invoke(self, state: dict[str, object]) -> dict[str, object]:
        output = dict(state)
        output.update(
            {
                "status": self._status.value,
                "final_answer": self._final_answer,
                "needs_clarification": self._needs_clarification,
                "clarification_question": self._clarification_question,
            }
        )
        return output


class _FailingGraph:
    def invoke(self, _state: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("graph failed")


def _fetch_artifacts(session: Session, chat_id: UUID) -> tuple[Chat | None, AgentRun, Message]:
    chat = session.get(Chat, chat_id)
    runs = session.scalars(select(AgentRun).where(AgentRun.chat_id == chat_id)).all()
    messages = session.scalars(select(Message).where(Message.chat_id == chat_id)).all()

    assert len(runs) == 1
    assert len(messages) == 1
    return chat, runs[0], messages[0]


def test_runtime_persists_completed_run(
    analytics_engine: Engine,
    persistence_service: RuntimePersistenceService,
) -> None:
    chat_id = uuid4()
    runtime_service = AgentRuntimeService(
        graph_factory=lambda: _TerminalGraph(status=RunStatus.COMPLETED, final_answer="completed"),
        persistence_service=persistence_service,
    )

    try:
        response = runtime_service.run(
            _request_payload(chat_id),
            verified_identity=_VERIFIED_IDENTITY,
        )
        assert response.status is RunStatus.COMPLETED

        with Session(bind=analytics_engine) as session:
            chat, run, message = _fetch_artifacts(session, chat_id)
            assert chat is not None
            assert run.status == "completed"
            assert run.error_code is None
            assert message.answer_text == "completed"
    finally:
        _cleanup_chat_records(analytics_engine, chat_id)


def test_runtime_persists_clarify_run(
    analytics_engine: Engine,
    persistence_service: RuntimePersistenceService,
) -> None:
    chat_id = uuid4()
    runtime_service = AgentRuntimeService(
        graph_factory=lambda: _TerminalGraph(
            status=RunStatus.CLARIFY,
            final_answer="Please clarify date range.",
            needs_clarification=True,
            clarification_question="Please clarify date range.",
        ),
        persistence_service=persistence_service,
    )

    try:
        response = runtime_service.run(
            _request_payload(chat_id),
            verified_identity=_VERIFIED_IDENTITY,
        )
        assert response.status is RunStatus.CLARIFY

        with Session(bind=analytics_engine) as session:
            _chat, run, message = _fetch_artifacts(session, chat_id)
            assert run.status == "clarification_needed"
            assert run.error_code is None
            assert message.answer_text == "Please clarify date range."
    finally:
        _cleanup_chat_records(analytics_engine, chat_id)


def test_runtime_persists_denied_run_as_failed_with_code(
    analytics_engine: Engine,
    persistence_service: RuntimePersistenceService,
) -> None:
    chat_id = uuid4()
    runtime_service = AgentRuntimeService(
        graph_factory=lambda: _TerminalGraph(
            status=RunStatus.DENIED,
            final_answer="Access denied.",
        ),
        persistence_service=persistence_service,
    )

    try:
        response = runtime_service.run(
            _request_payload(chat_id),
            verified_identity=_VERIFIED_IDENTITY,
        )
        assert response.status is RunStatus.DENIED

        with Session(bind=analytics_engine) as session:
            _chat, run, message = _fetch_artifacts(session, chat_id)
            assert run.status == "failed"
            assert run.error_code == "denied"
            assert message.answer_text == "Access denied."
    finally:
        _cleanup_chat_records(analytics_engine, chat_id)


def test_runtime_persists_failed_run_on_graph_exception(
    analytics_engine: Engine,
    persistence_service: RuntimePersistenceService,
) -> None:
    chat_id = uuid4()
    runtime_service = AgentRuntimeService(
        graph_factory=lambda: _FailingGraph(),
        persistence_service=persistence_service,
    )

    try:
        with pytest.raises(AgentRuntimeExecutionError):
            runtime_service.run(
                _request_payload(chat_id),
                verified_identity=_VERIFIED_IDENTITY,
            )

        with Session(bind=analytics_engine) as session:
            _chat, run, message = _fetch_artifacts(session, chat_id)
            assert run.status == "failed"
            assert run.error_code == "runtime_internal_error"
            assert message.answer_text is None
    finally:
        _cleanup_chat_records(analytics_engine, chat_id)
