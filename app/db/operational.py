from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_operational_engine() -> Engine:
    settings = get_settings()
    db_url = settings.database_url

    if db_url is None or not db_url.strip():
        raise ValueError("SMARTREST_DATABASE_URL or DATABASE_URL is not configured")

    return create_engine(
        db_url,
        pool_pre_ping=True,
        future=True,
    )

@lru_cache(maxsize=1)
def get_operational_session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_operational_engine(),
        class_=Session,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

def get_operational_session() -> Iterator[Session]:
    session = get_operational_session_factory()()
    try:
        yield session
    finally:
        session.close()
