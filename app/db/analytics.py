from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_chat_analytics_engine() -> Engine:
    settings = get_settings()
    db_url = settings.chat_analytics_database_url
    if db_url is None or not db_url.strip():
        raise ValueError(
            "SMARTREST_CHAT_ANALYTICS_DATABASE_URL or CHAT_ANALYTICS_DATABASE_URL is not configured"
        )

    return create_engine(db_url, pool_pre_ping=True, future=True)

@lru_cache(maxsize=1)
def get_chat_analytics_session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_chat_analytics_engine(),
        class_=Session,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

def get_chat_analytics_session() -> Iterator[Session]:
    session = get_chat_analytics_session_factory()()
    try:
        yield session
    finally:
        session.close()
