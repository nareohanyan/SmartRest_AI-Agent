from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

_SKIPPED_NODEIDS: set[str] = set()
_TIERED_MARKERS = ("integration", "post_sync")


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
    return os.getenv("SMARTREST_CHAT_ANALYTICS_DATABASE_URL") or os.getenv(
        "CHAT_ANALYTICS_DATABASE_URL"
    )


def _resolve_operational_database_url() -> str | None:
    return os.getenv("SMARTREST_DATABASE_URL") or os.getenv("DATABASE_URL")


def _require_reachable_database(db_url: str, error_message: str) -> None:
    engine = create_engine(db_url, future=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise pytest.UsageError(f"{error_message} Connection error: {exc}") from exc
    finally:
        engine.dispose()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-all-tests",
        action="store_true",
        default=False,
        help="Run unit, integration, and post-sync tests in a single pytest invocation.",
    )


def pytest_sessionstart(session: pytest.Session) -> None:
    _load_env_file_if_present()
    db_url = _resolve_chat_analytics_database_url()
    if db_url:
        os.environ["SMARTREST_CHAT_ANALYTICS_DATABASE_URL"] = db_url
        os.environ["CHAT_ANALYTICS_DATABASE_URL"] = db_url


@pytest.fixture(scope="session", autouse=True)
def _disable_runtime_skip_calls() -> Generator[None, None, None]:
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

    if config.option.run_all_tests:
        _enforce_selected_tier_dependencies(config, items)
        return

    if (config.option.markexpr or "").strip():
        _enforce_selected_tier_dependencies(config, items)
        return

    deselected = [
        item
        for item in items
        if any(item.get_closest_marker(marker) for marker in _TIERED_MARKERS)
    ]
    if not deselected:
        return

    selected = [item for item in items if item not in deselected]
    config.hook.pytest_deselected(items=deselected)
    items[:] = selected

    _enforce_selected_tier_dependencies(config, items)


def _enforce_selected_tier_dependencies(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    markexpr = (config.option.markexpr or "").strip()

    if markexpr:
        has_integration = "integration" in markexpr and "not integration" not in markexpr
        has_post_sync = "post_sync" in markexpr and "not post_sync" not in markexpr
    else:
        has_integration = any(item.get_closest_marker("integration") for item in items)
        has_post_sync = any(item.get_closest_marker("post_sync") for item in items)

    if has_integration:
        db_url = _resolve_chat_analytics_database_url()
        if not db_url:
            raise pytest.UsageError(
                "Integration tests require SMARTREST_CHAT_ANALYTICS_DATABASE_URL or "
                "CHAT_ANALYTICS_DATABASE_URL."
            )
        _require_reachable_database(
            db_url,
            "Integration tests require a reachable chat analytics Postgres database.",
        )

    if has_post_sync:
        db_url = _resolve_operational_database_url()
        if not db_url:
            raise pytest.UsageError(
                "Post-sync smoke tests require SMARTREST_DATABASE_URL or DATABASE_URL."
            )
        _require_reachable_database(
            db_url,
            "Post-sync smoke tests require a reachable local SmartRest/Postgres database.",
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
