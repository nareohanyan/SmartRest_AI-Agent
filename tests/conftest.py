from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

_SKIPPED_NODEIDS: set[str] = set()


def _load_env_file_if_present() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in os.environ:
            continue
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def _resolve_chat_analytics_database_url() -> str | None:
    return os.getenv("CHAT_ANALYTICS_DATABASE_URL") or os.getenv(
        "SMARTREST_CHAT_ANALYTICS_DATABASE_URL"
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    _load_env_file_if_present()
    db_url = _resolve_chat_analytics_database_url()
    if not db_url:
        raise pytest.UsageError(
            "CHAT_ANALYTICS_DATABASE_URL is required for full test runs. "
            "Skipping DB tests is disabled."
        )
    os.environ["CHAT_ANALYTICS_DATABASE_URL"] = db_url

    engine = create_engine(db_url, future=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise pytest.UsageError(
            "Chat analytics DB is unreachable. "
            "Skipping DB tests is disabled. "
            f"Connection error: {exc}"
        ) from exc
    finally:
        engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _disable_runtime_skip_calls() -> None:
    def _fail_skip(reason: str = "", *, allow_module_level: bool = False) -> None:
        _ = allow_module_level
        pytest.fail(
            "Skipping tests is disabled by project policy. "
            f"Found pytest.skip(...) call with reason: {reason}",
            pytrace=False,
        )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(pytest, "skip", _fail_skip)
    try:
        yield
    finally:
        monkeypatch.undo()


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    _ = config
    skip_marked = [
        item.nodeid
        for item in items
        if item.get_closest_marker("skip") or item.get_closest_marker("skipif")
    ]
    if skip_marked:
        joined = "\n".join(skip_marked)
        raise pytest.UsageError(
            "Skip markers are not allowed by project policy. "
            f"Found skip/skipif on:\n{joined}"
        )


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.skipped:
        _SKIPPED_NODEIDS.add(report.nodeid)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    _ = exitstatus
    if not _SKIPPED_NODEIDS:
        return

    terminal_reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if terminal_reporter is not None:
        terminal_reporter.write_sep("=", "Skipped tests are forbidden")
        for nodeid in sorted(_SKIPPED_NODEIDS):
            terminal_reporter.write_line(f"- {nodeid}")

    session.exitstatus = pytest.ExitCode.TESTS_FAILED
