from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_toon_lahmajo_engine() -> Engine:
    settings = get_settings()
    db_url = settings.toon_lahmajo_db_url
    if db_url is None or not db_url.strip():
        raise ValueError("SMARTREST_TOON_LAHMAJO_DB or TOON_LAHMAJO_DB is not configured")

    return create_engine(
        db_url,
        pool_pre_ping=True,
        future=True,
    )

