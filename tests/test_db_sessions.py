from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.db.analytics import (
    get_chat_analytics_engine,
    get_chat_analytics_session,
    get_chat_analytics_session_factory,
)
from app.db.operational import (
    get_operational_engine,
    get_operational_session,
    get_operational_session_factory,
)
from app.smartrest.models import get_sync_engine, get_sync_session_factory


@pytest.fixture(autouse=True)
def clear_cached_factories() -> Iterator[None]:
    get_settings.cache_clear()
    get_chat_analytics_engine.cache_clear()
    get_chat_analytics_session_factory.cache_clear()
    get_operational_engine.cache_clear()
    get_operational_session_factory.cache_clear()
    get_sync_session_factory.cache_clear()
    yield
    get_settings.cache_clear()
    get_chat_analytics_engine.cache_clear()
    get_chat_analytics_session_factory.cache_clear()
    get_operational_engine.cache_clear()
    get_operational_session_factory.cache_clear()
    get_sync_session_factory.cache_clear()


def test_settings_load_db_urls_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    operational_db_url = "sqlite+pysqlite:///:memory:"
    chat_analytics_db_url = "sqlite+pysqlite:///:memory:"
    monkeypatch.setenv("SMARTREST_DATABASE_URL", operational_db_url)
    monkeypatch.setenv("SMARTREST_CHAT_ANALYTICS_DATABASE_URL", chat_analytics_db_url)
    monkeypatch.delenv("CHAT_ANALYTICS_DATABASE_URL", raising=False)

    settings = get_settings()

    assert settings.database_url == operational_db_url
    assert settings.chat_analytics_database_url == chat_analytics_db_url


def test_engine_factories_are_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMARTREST_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("SMARTREST_CHAT_ANALYTICS_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.delenv("CHAT_ANALYTICS_DATABASE_URL", raising=False)

    chat_engine_1 = get_chat_analytics_engine()
    chat_engine_2 = get_chat_analytics_engine()
    operational_engine_1 = get_operational_engine()
    operational_engine_2 = get_operational_engine()
    sync_engine_1 = get_sync_engine()
    sync_engine_2 = get_sync_engine()

    assert chat_engine_1 is chat_engine_2
    assert operational_engine_1 is operational_engine_2
    assert sync_engine_1 is operational_engine_1
    assert sync_engine_2 is operational_engine_2


def test_sync_session_factory_reuses_operational_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMARTREST_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("SMARTREST_CHAT_ANALYTICS_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.delenv("CHAT_ANALYTICS_DATABASE_URL", raising=False)

    sync_factory = get_sync_session_factory()
    operational_factory = get_operational_session_factory()

    assert sync_factory is operational_factory


def test_session_dependencies_yield_working_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMARTREST_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("SMARTREST_CHAT_ANALYTICS_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.delenv("CHAT_ANALYTICS_DATABASE_URL", raising=False)

    chat_gen = get_chat_analytics_session()
    chat_session = next(chat_gen)
    assert chat_session.execute(text("SELECT 1")).scalar_one() == 1
    with pytest.raises(StopIteration):
        next(chat_gen)

    operational_gen = get_operational_session()
    operational_session = next(operational_gen)
    assert operational_session.execute(text("SELECT 1")).scalar_one() == 1
    with pytest.raises(StopIteration):
        next(operational_gen)
