"""FastAPI application factory."""

from fastapi import FastAPI

from app.core.config import get_settings


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    settings = get_settings()
    app = FastAPI(title=settings.app_name)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.app_env}

    return app
