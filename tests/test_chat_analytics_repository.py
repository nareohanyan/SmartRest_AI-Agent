from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.orm import Session

from app.chat_analytics.models import AgentRun, Base, Message, Thread
from app.persistence.chat_analytics_repository import ChatAnalyticsRepository
from app.persistence.errors import PersistenceNotFoundError, PersistenceValidationError
from app.schemas.agent import RunStatus


def _chat_analytics_database_url() -> str:
    db_url = os.getenv("CHAT_ANALYTICS_DATABASE_URL") or os.getenv(
        "SMARTREST_CHAT_ANALYTICS_DATABASE_URL"
    )
    if not db_url:
        pytest.skip("CHAT_ANALYTICS_DATABASE_URL is not set; skipping repository DB tests.")
    return db_url


@pytest.fixture(scope="session")
def analytics_engine() -> Iterator[Engine]:
    engine = create_engine(_chat_analytics_database_url(), future=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Chat analytics DB is not reachable: {exc}")

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(analytics_engine: Engine) -> Iterator[Session]:
    connection = analytics_engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_get_or_create_thread_is_idempotent(db_session: Session) -> None:
    repo = ChatAnalyticsRepository(db_session)
    thread_id = uuid4()

    first = repo.get_or_create_thread(
        thread_id=thread_id,
        user_id="101",
        profile_id="201",
        profile_nick="chef_nick",
        title="Thread A",
    )
    second = repo.get_or_create_thread(
        thread_id=thread_id,
        user_id=101,
        profile_id=201,
        profile_nick="chef_nick",
        title="Thread B",
    )

    assert first.id == second.id == thread_id
    count = db_session.scalar(
        select(func.count()).select_from(Thread).where(Thread.id == thread_id)
    )
    assert count == 1


def test_get_or_create_thread_rejects_non_integer_identity(db_session: Session) -> None:
    repo = ChatAnalyticsRepository(db_session)

    with pytest.raises(PersistenceValidationError):
        repo.get_or_create_thread(
            thread_id=uuid4(),
            user_id="u-1",
            profile_id="201",
            profile_nick="chef_nick",
        )


def test_create_run_started_requires_existing_thread(db_session: Session) -> None:
    repo = ChatAnalyticsRepository(db_session)

    with pytest.raises(PersistenceNotFoundError):
        repo.create_run_started(
            thread_id=uuid4(),
            user_id=100,
            profile_id=200,
            profile_nick="chef_nick",
        )


def test_create_run_and_update_terminal_status(db_session: Session) -> None:
    repo = ChatAnalyticsRepository(db_session)
    thread = repo.get_or_create_thread(
        thread_id=uuid4(),
        user_id=100,
        profile_id=200,
        profile_nick="chef_nick",
    )
    run = repo.create_run_started(
        thread_id=thread.id,
        user_id=100,
        profile_id=200,
        profile_nick="chef_nick",
        intent="get_kpi",
    )

    assert run.status == "started"

    updated = repo.update_run_terminal_status(
        run_id=run.id,
        status=RunStatus.REJECTED,
        error_message="unsupported_report",
    )

    assert updated.status == "failed"
    assert updated.error_code == "rejected"
    assert updated.error_message == "unsupported_report"

    stored = db_session.get(AgentRun, run.id)
    assert stored is not None
    assert stored.status == "failed"


def test_write_message_persists_payload_and_updates_last_message_at(db_session: Session) -> None:
    repo = ChatAnalyticsRepository(db_session)
    thread = repo.get_or_create_thread(
        thread_id=uuid4(),
        user_id=300,
        profile_id=400,
        profile_nick="ops_user",
    )
    run = repo.create_run_started(
        thread_id=thread.id,
        user_id=300,
        profile_id=400,
        profile_nick="ops_user",
    )

    message = repo.write_message(
        thread_id=thread.id,
        run_id=run.id,
        question="How many orders yesterday?",
        answer="345",
    )

    assert message.question == "How many orders yesterday?"
    assert message.answer == "345"

    stored_message = db_session.get(Message, message.id)
    assert stored_message is not None

    stored_thread = db_session.get(Thread, thread.id)
    assert stored_thread is not None
    assert stored_thread.last_message_at is not None
