from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, delete, select, text
from sqlalchemy.orm import Session

from app.api.schemas import AgentRunRequest
from app.chat_analytics.models import AgentRun, Feedback, Message, Thread, ThreadHistory
from app.persistence.runtime_persistence import RuntimePersistenceService
from app.persistence.thread_id_mapper import to_internal_thread_uuid
from app.schemas.agent import RunStatus
from app.services.agent_runtime import AgentRuntimeExecutionError, AgentRuntimeService


def _chat_analytics_database_url() -> str:
    db_url = os.getenv("CHAT_ANALYTICS_DATABASE_URL") or os.getenv(
        "SMARTREST_CHAT_ANALYTICS_DATABASE_URL"
    )
    if not db_url:
        pytest.skip("CHAT_ANALYTICS_DATABASE_URL is not set; skipping DB integration tests.")
    return db_url


@pytest.fixture(scope="session")
def analytics_engine() -> Iterator[Engine]:
    engine = create_engine(_chat_analytics_database_url(), future=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Chat analytics DB is not reachable: {exc}")

    yield engine
    engine.dispose()


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


def _request_payload(thread_id: str) -> AgentRunRequest:
    return AgentRunRequest.model_validate(
        {
            "thread_id": thread_id,
            "user_question": "What were total sales 2026-03-01 to 2026-03-07?",
            "scope_request": {
                "user_id": "101",
                "profile_id": "201",
                "profile_nick": "nick",
                "metadata": {},
            },
        }
    )


def _cleanup_thread_records(engine: Engine, thread_id: UUID) -> None:
    with Session(bind=engine) as session:
        session.execute(delete(Feedback).where(Feedback.thread_id == thread_id))
        session.execute(delete(Message).where(Message.thread_id == thread_id))
        session.execute(delete(AgentRun).where(AgentRun.thread_id == thread_id))
        session.execute(delete(ThreadHistory).where(ThreadHistory.thread_id == thread_id))
        session.execute(delete(Thread).where(Thread.id == thread_id))
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


def _fetch_artifacts(session: Session, thread_id: UUID) -> tuple[Thread | None, AgentRun, Message]:
    thread = session.get(Thread, thread_id)
    runs = session.scalars(select(AgentRun).where(AgentRun.thread_id == thread_id)).all()
    messages = session.scalars(select(Message).where(Message.thread_id == thread_id)).all()

    assert len(runs) == 1
    assert len(messages) == 1
    return thread, runs[0], messages[0]


def test_runtime_persists_completed_run(
    analytics_engine: Engine,
    persistence_service: RuntimePersistenceService,
) -> None:
    external_thread_id = f"e3-completed-{uuid4().hex}"
    internal_thread_id = to_internal_thread_uuid(external_thread_id)
    runtime_service = AgentRuntimeService(
        graph_factory=lambda: _TerminalGraph(status=RunStatus.COMPLETED, final_answer="completed"),
        persistence_service=persistence_service,
    )

    try:
        response = runtime_service.run(_request_payload(external_thread_id))
        assert response.status is RunStatus.COMPLETED

        with Session(bind=analytics_engine) as session:
            thread, run, message = _fetch_artifacts(session, internal_thread_id)
            assert thread is not None
            assert run.status == "completed"
            assert run.error_code is None
            assert message.answer == "completed"
    finally:
        _cleanup_thread_records(analytics_engine, internal_thread_id)


def test_runtime_persists_clarify_run(
    analytics_engine: Engine,
    persistence_service: RuntimePersistenceService,
) -> None:
    external_thread_id = f"e3-clarify-{uuid4().hex}"
    internal_thread_id = to_internal_thread_uuid(external_thread_id)
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
        response = runtime_service.run(_request_payload(external_thread_id))
        assert response.status is RunStatus.CLARIFY

        with Session(bind=analytics_engine) as session:
            _thread, run, message = _fetch_artifacts(session, internal_thread_id)
            assert run.status == "clarification_needed"
            assert run.error_code is None
            assert message.answer == "Please clarify date range."
    finally:
        _cleanup_thread_records(analytics_engine, internal_thread_id)


def test_runtime_persists_denied_run_as_failed_with_code(
    analytics_engine: Engine,
    persistence_service: RuntimePersistenceService,
) -> None:
    external_thread_id = f"e3-denied-{uuid4().hex}"
    internal_thread_id = to_internal_thread_uuid(external_thread_id)
    runtime_service = AgentRuntimeService(
        graph_factory=lambda: _TerminalGraph(
            status=RunStatus.DENIED,
            final_answer="Access denied.",
        ),
        persistence_service=persistence_service,
    )

    try:
        response = runtime_service.run(_request_payload(external_thread_id))
        assert response.status is RunStatus.DENIED

        with Session(bind=analytics_engine) as session:
            _thread, run, message = _fetch_artifacts(session, internal_thread_id)
            assert run.status == "failed"
            assert run.error_code == "denied"
            assert message.answer == "Access denied."
    finally:
        _cleanup_thread_records(analytics_engine, internal_thread_id)


def test_runtime_persists_failed_run_on_graph_exception(
    analytics_engine: Engine,
    persistence_service: RuntimePersistenceService,
) -> None:
    external_thread_id = f"e3-failed-{uuid4().hex}"
    internal_thread_id = to_internal_thread_uuid(external_thread_id)
    runtime_service = AgentRuntimeService(
        graph_factory=lambda: _FailingGraph(),
        persistence_service=persistence_service,
    )

    try:
        with pytest.raises(AgentRuntimeExecutionError):
            runtime_service.run(_request_payload(external_thread_id))

        with Session(bind=analytics_engine) as session:
            _thread, run, message = _fetch_artifacts(session, internal_thread_id)
            assert run.status == "failed"
            assert run.error_code == "runtime_internal_error"
            assert message.answer is None
    finally:
        _cleanup_thread_records(analytics_engine, internal_thread_id)
