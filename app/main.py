"""Application entrypoint."""

from app.api.app import create_app
from app.core.logging import configure_logging

configure_logging()
app = create_app()


def main() -> None:
    """Local manual run helper."""
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
