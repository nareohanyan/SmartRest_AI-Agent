from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

pytestmark = pytest.mark.integration

REQUIRED_TABLES = {
    "chats",
    "chat_events",
    "agent_runs",
    "messages",
    "feedback",
    "chat_metadata",
}

EXPECTED_INDEXES: dict[str, set[str]] = {
    "chats": {
        "ix_chats_user_profile_created_at",
        "ix_chats_status_created_at",
        "ix_chats_last_message_at",
    },
    "chat_events": {"ix_chat_events_chat_created_at"},
    "agent_runs": {
        "ix_agent_runs_chat_created_at",
        "ix_agent_runs_status_created_at",
    },
    "messages": {
        "ix_messages_chat_created_at",
        "ix_messages_run_id",
        "ix_messages_status_created_at",
    },
    "feedback": {"ix_feedback_message_id", "ix_feedback_chat_created_at"},
    "chat_metadata": {"ix_chat_metadata_chat_key"},
}

EXPECTED_CHECK_CONSTRAINTS: dict[str, set[str]] = {
    "chats": {"ck_chats_status"},
    "chat_events": {"ck_chat_events_event_type"},
    "agent_runs": {"ck_agent_runs_status"},
    "messages": {"ck_messages_status"},
    "feedback": {"ck_feedback_feedback_type"},
}


def _chat_analytics_database_url() -> str:
    db_url = os.getenv("SMARTREST_CHAT_ANALYTICS_DATABASE_URL") or os.getenv(
        "CHAT_ANALYTICS_DATABASE_URL"
    )
    if not db_url:
        raise pytest.UsageError(
            "Migration integration tests require SMARTREST_CHAT_ANALYTICS_DATABASE_URL or "
            "CHAT_ANALYTICS_DATABASE_URL."
        )
    return db_url


def _migration_database_url(base_url: str, schema_name: str) -> str:
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}options=-csearch_path={schema_name}"


@contextmanager
def _override_chat_analytics_db_url(db_url: str) -> Iterator[None]:
    original_prefixed = os.environ.get("SMARTREST_CHAT_ANALYTICS_DATABASE_URL")
    original_legacy = os.environ.get("CHAT_ANALYTICS_DATABASE_URL")
    os.environ["SMARTREST_CHAT_ANALYTICS_DATABASE_URL"] = db_url
    os.environ["CHAT_ANALYTICS_DATABASE_URL"] = db_url
    try:
        yield
    finally:
        if original_prefixed is None:
            os.environ.pop("SMARTREST_CHAT_ANALYTICS_DATABASE_URL", None)
        else:
            os.environ["SMARTREST_CHAT_ANALYTICS_DATABASE_URL"] = original_prefixed
        if original_legacy is None:
            os.environ.pop("CHAT_ANALYTICS_DATABASE_URL", None)
        else:
            os.environ["CHAT_ANALYTICS_DATABASE_URL"] = original_legacy


def _alembic_config() -> Config:
    repo_root = Path(__file__).resolve().parents[1]
    return Config(str(repo_root / "alembic.ini"))


def _upgrade_head(migration_db_url: str) -> None:
    with _override_chat_analytics_db_url(migration_db_url):
        command.upgrade(_alembic_config(), "head")


def _downgrade_base(migration_db_url: str) -> None:
    with _override_chat_analytics_db_url(migration_db_url):
        command.downgrade(_alembic_config(), "base")


@pytest.fixture
def isolated_schema_db_url() -> Iterator[tuple[str, str]]:
    base_db_url = _chat_analytics_database_url()
    schema_name = f"test_migration_{uuid4().hex}"
    base_engine = create_engine(base_db_url, future=True)
    schema_created = False
    try:
        try:
            with base_engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
            schema_created = True
        except Exception as exc:
            raise pytest.UsageError(
                "Chat analytics migration tests require a reachable Postgres database. "
                f"Connection error: {exc}"
            ) from exc
        migration_db_url = _migration_database_url(base_db_url, schema_name)
        yield schema_name, migration_db_url
    finally:
        if schema_created:
            with base_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        base_engine.dispose()


def test_chat_analytics_migrations_upgrade_downgrade_lifecycle(
    isolated_schema_db_url: tuple[str, str],
) -> None:
    schema_name, migration_db_url = isolated_schema_db_url
    migration_engine = create_engine(migration_db_url, future=True)
    try:
        _upgrade_head(migration_db_url)
        inspector = inspect(migration_engine)
        tables_after_upgrade = set(inspector.get_table_names(schema=schema_name))
        assert REQUIRED_TABLES.issubset(tables_after_upgrade)

        _downgrade_base(migration_db_url)
        inspector = inspect(migration_engine)
        tables_after_downgrade = set(inspector.get_table_names(schema=schema_name))
        assert REQUIRED_TABLES.isdisjoint(tables_after_downgrade)

        _upgrade_head(migration_db_url)
        inspector = inspect(migration_engine)
        tables_after_reupgrade = set(inspector.get_table_names(schema=schema_name))
        assert REQUIRED_TABLES.issubset(tables_after_reupgrade)
    finally:
        migration_engine.dispose()


def test_chat_analytics_migration_schema_integrity(
    isolated_schema_db_url: tuple[str, str],
) -> None:
    schema_name, migration_db_url = isolated_schema_db_url
    _upgrade_head(migration_db_url)
    migration_engine = create_engine(migration_db_url, future=True)
    try:
        inspector = inspect(migration_engine)
        tables = set(inspector.get_table_names(schema=schema_name))
        assert REQUIRED_TABLES.issubset(tables)

        for table_name, expected_indexes in EXPECTED_INDEXES.items():
            index_names = {
                index["name"] for index in inspector.get_indexes(table_name, schema=schema_name)
            }
            assert expected_indexes.issubset(index_names)

        for table_name, expected_constraints in EXPECTED_CHECK_CONSTRAINTS.items():
            check_names = {
                check["name"]
                for check in inspector.get_check_constraints(table_name, schema=schema_name)
            }
            assert expected_constraints.issubset(check_names)
    finally:
        migration_engine.dispose()
