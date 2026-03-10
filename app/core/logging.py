"""Logging setup."""

import logging

from app.core.config import get_settings


def configure_logging() -> None:
    """Configure global logging once at startup."""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
