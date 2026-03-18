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

REQUIRED_TABLES = {
    "threads",
    "thread_history",
    "agent_runs",
    "messages",
    "feedback",
}

EXPECTED_INDEXES: dict[str, set[str]] = {
    "threads": {
        "ix_threads_user_profile_created_at",
        "ix_threads_status_created_at",
        "ix_threads_last_message_at",
    },
    "thread_history": {"ix_threads_history_thread_created_at"},
    "agent_runs": {
        "ix_agent_runs_thread_created_at",
        "ix_agent_runs_status_created_at",
    },
    "messages": {"ix_messages_thread_created_at", "ix_messages_run_id"},
}

EXPECTED_CHECK_CONSTRAINTS: dict[str, set[str]] = {
    "threads": {"ck_threads_status"},
    "thread_history": {"ck_threads_history_event_type"},
    "agent_runs": {"ck_agent_runs_status"},
}


def _chat_analytics_database_url() -> str:
    db_url = os.getenv("CHAT_ANALYTICS_DATABASE_URL") or os.getenv(
        "SMARTREST_CHAT_ANALYTICS_DATABASE_URL"
    )
    if not db_url:
        pytest.skip("CHAT_ANALYTICS_DATABASE_URL is not set; skipping migration tests.")
    return db_url


def _migration_database_url(base_url: str, schema_name: str) -> str:
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}options=-csearch_path={schema_name}"


@contextmanager
def _override_chat_analytics_db_url(db_url: str) -> Iterator[None]:
    original = os.environ.get("CHAT_ANALYTICS_DATABASE_URL")
    os.environ["CHAT_ANALYTICS_DATABASE_URL"] = db_url
    try:
        yield
    finally:
        if original is None:
            os.environ.pop("CHAT_ANALYTICS_DATABASE_URL", None)
        else:
            os.environ["CHAT_ANALYTICS_DATABASE_URL"] = original


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
            pytest.skip(f"Chat analytics DB is not reachable: {exc}")
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
