from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest

import app.agent.report_tools as report_tools
from app.core.config import get_settings
from app.reports import SmartRestReportBackendUnsupportedError
from app.schemas.reports import ReportFilters, ReportRequest, ReportType
from app.schemas.tools import AccessStatus, ResolveScopeRequest, RunReportRequest


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _scope_request() -> ResolveScopeRequest:
    return ResolveScopeRequest.model_validate(
        {
            "user_id": 101,
            "profile_id": 201,
            "profile_nick": "nick",
            "metadata": {},
        }
    )


def _report_request() -> RunReportRequest:
    return RunReportRequest(
        user_id=101,
        profile_id=201,
        profile_nick="nick",
        request=ReportRequest(
            report_id=ReportType.SALES_TOTAL,
            filters=ReportFilters(date_from="2026-03-01", date_to="2026-03-07"),
        ),
    )


def test_resolve_scope_db_strict_denies_when_db_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RaisingResolver:
        def resolve(self, **_kwargs: object) -> object:
            raise RuntimeError("db unavailable")

    monkeypatch.setenv("SMARTREST_SCOPE_BACKEND_MODE", "db_strict")
    monkeypatch.setattr(report_tools, "get_canonical_identity_resolver", lambda: _RaisingResolver())

    response = report_tools.resolve_scope_tool(_scope_request())

    assert response.status is AccessStatus.DENIED
    assert response.denial_reason == "scope_db_unavailable"


def test_resolve_scope_db_sets_canonical_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    @dataclass(frozen=True)
    class _Resolution:
        source_system_id: int
        canonical_profile_id: int
        canonical_user_id: int

    class _Resolver:
        def resolve(self, **_kwargs: object) -> _Resolution:
            return _Resolution(
                source_system_id=11,
                canonical_profile_id=22,
                canonical_user_id=33,
            )

    monkeypatch.setenv("SMARTREST_SCOPE_BACKEND_MODE", "db_strict")
    monkeypatch.setattr(report_tools, "get_canonical_identity_resolver", lambda: _Resolver())

    response = report_tools.resolve_scope_tool(_scope_request())

    assert response.status is AccessStatus.GRANTED
    assert response.source_system_id == 11
    assert response.canonical_profile_id == 22
    assert response.canonical_user_id == 33


def test_run_report_db_strict_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMARTREST_REPORT_BACKEND_MODE", "db_strict")

    def _raise_backend(*_args: object, **_kwargs: object) -> object:
        raise SmartRestReportBackendUnsupportedError("unsupported")

    monkeypatch.setattr(report_tools, "run_smartrest_report", _raise_backend)

    with pytest.raises(SmartRestReportBackendUnsupportedError):
        report_tools.run_report_tool(_report_request())


def test_run_report_strict_environment_rejects_fallback_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMARTREST_APP_ENV", "staging")
    monkeypatch.setenv("SMARTREST_REPORT_BACKEND_MODE", "db_strict")

    monkeypatch.setattr(
        report_tools,
        "run_smartrest_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            SmartRestReportBackendUnsupportedError("unsupported")
        ),
    )

    with pytest.raises(SmartRestReportBackendUnsupportedError):
        report_tools.run_report_tool(_report_request())


def test_resolve_scope_strict_environment_rejects_mock_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMARTREST_APP_ENV", "local_acceptance")
    monkeypatch.setenv("SMARTREST_SCOPE_BACKEND_MODE", "db_strict")
    monkeypatch.setattr(
        report_tools,
        "get_canonical_identity_resolver",
        lambda: type(
            "_Resolver",
            (),
            {
                "resolve": staticmethod(
                    lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("db unavailable"))
                )
            },
        )(),
    )

    response = report_tools.resolve_scope_tool(_scope_request())

    assert response.status is AccessStatus.DENIED
    assert response.denial_reason == "scope_db_unavailable"
