from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.orm import Session

from app.chat_analytics.models import AgentRun, Base, Chat, Message
from app.persistence.chat_analytics_repository import ChatAnalyticsRepository
from app.persistence.errors import PersistenceNotFoundError, PersistenceValidationError
from app.schemas.agent import RunStatus


def _chat_analytics_database_url() -> str:
    db_url = os.getenv("SMARTREST_CHAT_ANALYTICS_DATABASE_URL") or os.getenv(
        "CHAT_ANALYTICS_DATABASE_URL"
    )
    if not db_url:
        pytest.skip("CHAT_ANALYTICS_DATABASE_URL is not set; skipping repository DB tests.")
    return db_url


def _schema_scoped_database_url(base_url: str, schema_name: str) -> str:
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}options=-csearch_path={schema_name}"


@pytest.fixture(scope="session")
def analytics_engine() -> Iterator[Engine]:
    base_db_url = _chat_analytics_database_url()
    schema_name = f"test_repo_{uuid4().hex}"
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


def test_get_or_create_chat_is_idempotent(db_session: Session) -> None:
    repo = ChatAnalyticsRepository(db_session)
    chat_id = uuid4()

    first = repo.get_or_create_chat(
        chat_id=chat_id,
        user_id="101",
        profile_id="201",
        profile_nick="chef_nick",
        title="Chat A",
    )
    second = repo.get_or_create_chat(
        chat_id=chat_id,
        user_id=101,
        profile_id=201,
        profile_nick="chef_nick",
        title="Chat B",
    )

    assert first.id == second.id == chat_id
    count = db_session.scalar(
        select(func.count()).select_from(Chat).where(Chat.id == chat_id)
    )
    assert count == 1


def test_get_or_create_chat_rejects_non_integer_identity(db_session: Session) -> None:
    repo = ChatAnalyticsRepository(db_session)

    with pytest.raises(PersistenceValidationError):
        repo.get_or_create_chat(
            chat_id=uuid4(),
            user_id="u-1",
            profile_id="201",
            profile_nick="chef_nick",
        )


def test_create_run_started_requires_existing_chat(db_session: Session) -> None:
    repo = ChatAnalyticsRepository(db_session)

    with pytest.raises(PersistenceNotFoundError):
        repo.create_run_started(
            chat_id=uuid4(),
            user_id=100,
            profile_id=200,
            profile_nick="chef_nick",
        )


def test_create_run_and_update_terminal_status(db_session: Session) -> None:
    repo = ChatAnalyticsRepository(db_session)
    chat = repo.get_or_create_chat(
        chat_id=uuid4(),
        user_id=100,
        profile_id=200,
        profile_nick="chef_nick",
    )
    run = repo.create_run_started(
        chat_id=chat.id,
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
    chat = repo.get_or_create_chat(
        chat_id=uuid4(),
        user_id=300,
        profile_id=400,
        profile_nick="ops_user",
    )
    run = repo.create_run_started(
        chat_id=chat.id,
        user_id=300,
        profile_id=400,
        profile_nick="ops_user",
    )

    message = repo.write_message(
        chat_id=chat.id,
        run_id=run.id,
        question_text="How many orders yesterday?",
        answer_text="345",
    )

    assert message.question_text == "How many orders yesterday?"
    assert message.answer_text == "345"

    stored_message = db_session.get(Message, message.id)
    assert stored_message is not None

    stored_chat = db_session.get(Chat, chat.id)
    assert stored_chat is not None
    assert stored_chat.last_message_at is not None
