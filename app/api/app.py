"""FastAPI application factory."""

from fastapi import FastAPI

from app.api.routes.agent import router as agent_router
from app.core.config import get_settings
from app.core.runtime_policy import validate_runtime_settings


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    settings = get_settings()
    validate_runtime_settings(settings)
    app = FastAPI(title=settings.app_name)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "environment": settings.app_env}

    app.include_router(agent_router)

    return app
