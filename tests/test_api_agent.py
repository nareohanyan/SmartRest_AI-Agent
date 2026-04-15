from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.agent.graph as graph_module
import app.agent.report_tools as report_tools
from app.agent.tools import business_insights as business_insights_tools
from app.agent.tools import retrieval as retrieval_tools
from app.api.app import create_app
from app.api.routes.agent import (
    _get_platform_admin_dependency,
    _get_runtime_service,
    _get_subscription_service,
)
from app.api.schemas import AgentRunRequest, PlatformAdminRunRequest
from app.core.auth import (
    build_canonical_payload,
    build_platform_admin_canonical_payload,
    sign_payload_token,
)
from app.core.config import get_settings
from app.schemas.analysis import (
    BreakdownItem,
    BreakdownResponse,
    CustomerSummaryResponse,
    ItemPerformanceItem,
    ItemPerformanceMetric,
    ItemPerformanceResponse,
    MetricName,
    TimeseriesPoint,
    TimeseriesResponse,
    TotalMetricResponse,
)
from app.schemas.reports import ReportMetric, ReportResult, ReportType
from app.schemas.subscription import SubscriptionAccessDecision
from app.schemas.tools import RunReportResponse
from app.services.agent_runtime import AgentRuntimeExecutionError
from app.services.platform_admin import PlatformAdminProfileSummary

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def app() -> FastAPI:
    return create_app()


def _missing_openai_key() -> Any:
    raise ValueError("OPENAI_API_KEY is not configured.")


@pytest.fixture(autouse=True)
def _disable_openai_client(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setattr(graph_module, "get_llm_client", _missing_openai_key)
    monkeypatch.setenv("SMARTREST_AUTH_SECRET_KEY", "test-secret")
    monkeypatch.setenv("SMARTREST_PLATFORM_ADMIN_SECRET_KEY", "admin-secret")
    monkeypatch.setattr(
        report_tools,
        "get_canonical_identity_resolver",
        lambda: type(
            "_Resolver",
            (),
            {
                "resolve": staticmethod(
                    lambda **kwargs: None
                    if kwargs.get("profile_id") == 999
                    else type(
                        "_Resolution",
                        (),
                        {
                            "source_system_id": 1,
                            "canonical_profile_id": 1,
                            "canonical_user_id": 1,
                        },
                    )()
                )
            },
        )(),
    )
    monkeypatch.setattr(report_tools, "run_smartrest_report", _fake_run_smartrest_report)
    monkeypatch.setattr(
        retrieval_tools,
        "get_live_analytics_service",
        lambda: _FakeLiveAnalyticsService(),
    )
    monkeypatch.setattr(
        business_insights_tools,
        "LiveBusinessToolsService",
        lambda: _FakeBusinessToolsService(),
    )
    graph_module.get_tool_registry.cache_clear()
    try:
        yield
    finally:
        graph_module.get_tool_registry.cache_clear()
        get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _allow_subscription_access(app: FastAPI) -> Iterator[None]:
    class _AllowingSubscriptionService:
        def evaluate_access(self, _verified_identity: Any) -> SubscriptionAccessDecision:
            return SubscriptionAccessDecision(
                allowed=True,
                reason_code="subscription_allowed",
                reason_message="AI agent subscription is active.",
            )

    async def _override_subscription_service() -> _AllowingSubscriptionService:
        return _AllowingSubscriptionService()

    app.dependency_overrides[_get_subscription_service] = _override_subscription_service
    try:
        yield
    finally:
        app.dependency_overrides.pop(_get_subscription_service, None)


def _auth_payload(
    *,
    profile_nick: str = "nick",
    user_id: int = 101,
    profile_id: int = 201,
    current_timestamp: int | None = None,
) -> dict[str, Any]:
    issued_at = current_timestamp if current_timestamp is not None else int(time.time())
    canonical_payload = build_canonical_payload(
        current_timestamp=issued_at,
        profile_nick=profile_nick,
        profile_id=profile_id,
        user_id=user_id,
    )
    return {
        "profile_nick": profile_nick,
        "user_id": user_id,
        "profile_id": profile_id,
        "current_timestamp": issued_at,
        "token": sign_payload_token("test-secret", canonical_payload),
    }


@pytest.fixture
async def api_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def _request_payload(
    question: str,
    *,
    metadata: dict[str, str] | None = None,
    profile_id: int = 201,
) -> dict[str, Any]:
    return {
        "chat_id": "11111111-1111-1111-1111-111111111111",
        "user_question": question,
        "auth": _auth_payload(profile_id=profile_id),
        "scope_request": {
            "user_id": 101,
            "profile_id": profile_id,
            "profile_nick": "nick",
            "metadata": metadata or {},
        },
    }


def _admin_auth_payload(
    *,
    admin_id: str = "owner",
    current_timestamp: int | None = None,
) -> dict[str, Any]:
    issued_at = current_timestamp if current_timestamp is not None else int(time.time())
    canonical_payload = build_platform_admin_canonical_payload(
        current_timestamp=issued_at,
        admin_id=admin_id,
    )
    return {
        "admin_id": admin_id,
        "current_timestamp": issued_at,
        "token": sign_payload_token("admin-secret", canonical_payload),
    }


def _admin_run_payload(
    question: str,
    *,
    target_profile_id: int = 98,
    target_profile_nick: str = "tunlahmajo_1681123576",
    target_user_id: int = 101,
) -> dict[str, Any]:
    return {
        "chat_id": "11111111-1111-1111-1111-111111111111",
        "user_question": question,
        "admin_auth": _admin_auth_payload(),
        "target_profile_id": target_profile_id,
        "target_profile_nick": target_profile_nick,
        "target_user_id": target_user_id,
        "metadata": {},
    }


async def test_supported_request_returns_completed_contract(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/agent/run",
        json=_request_payload("What were total sales 2026-03-01 to 2026-03-07?"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["chat_id"] == "11111111-1111-1111-1111-111111111111"
    assert isinstance(payload["run_id"], str) and payload["run_id"]
    assert payload["status"] == "completed"
    assert payload["answer"]
    assert payload["selected_report_id"] == "sales_total"
    assert payload["applied_filters"]["date_from"] == "2026-03-01"
    assert payload["applied_filters"]["date_to"] == "2026-03-07"
    assert payload["needs_clarification"] is False
    assert payload["clarification_question"] is None


async def test_missing_date_returns_clarify_response(api_client: AsyncClient) -> None:
    response = await api_client.post("/agent/run", json=_request_payload("What were total sales?"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "clarify"
    assert payload["needs_clarification"] is True
    assert payload["clarification_question"]
    assert "date range" in payload["clarification_question"].lower()


async def test_smalltalk_returns_onboarding_contract(api_client: AsyncClient) -> None:
    response = await api_client.post("/agent/run", json=_request_payload("բարև"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "onboarding"
    assert payload["needs_clarification"] is False
    assert payload["clarification_question"] is None
    assert payload["answer"] == "Ողջու՜յն։ Ինչո՞վ կարող եմ օգնել ձեզ այսօր։"


async def test_smalltalk_in_russian_returns_onboarding_contract(api_client: AsyncClient) -> None:
    response = await api_client.post("/agent/run", json=_request_payload("здравствуйте"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "onboarding"
    assert payload["needs_clarification"] is False
    assert payload["clarification_question"] is None
    assert payload["answer"] == "Здравствуйте. Чем я могу вам сегодня помочь?"


async def test_casual_english_smalltalk_returns_onboarding_contract(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post("/agent/run", json=_request_payload("hello what's up"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "onboarding"
    assert payload["needs_clarification"] is False
    assert payload["clarification_question"] is None
    assert payload["answer"] == "Hello. Nice to see you here."


async def test_casual_armenian_smalltalk_returns_onboarding_contract(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post("/agent/run", json=_request_payload("ինչ կա"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "onboarding"
    assert payload["needs_clarification"] is False
    assert payload["clarification_question"] is None
    assert payload["answer"] == "Ողջու՜յն։ Ինչո՞վ կարող եմ օգնել ձեզ այսօր։"


async def test_typo_russian_greeting_returns_onboarding_contract(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post("/agent/run", json=_request_payload("здраствуйте"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "onboarding"
    assert payload["needs_clarification"] is False
    assert payload["clarification_question"] is None
    assert payload["answer"] == "Здравствуйте. Чем я могу вам сегодня помочь?"


async def test_unsupported_request_returns_rejected_status(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/agent/run",
        json=_request_payload("Show payroll tax trend 2026-03-01 to 2026-03-07."),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "rejected"
    assert payload["needs_clarification"] is False
    assert payload["selected_report_id"] is None


async def test_denied_scope_returns_denied_and_blocks_report_path(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post(
        "/agent/run",
        json=_request_payload(
            "What were total sales 2026-03-01 to 2026-03-07?",
            profile_id=999,
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "denied"
    assert payload["selected_report_id"] is None
    assert payload["answer"] is not None


@pytest.fixture(autouse=True)
def _platform_admin_dependency(app: FastAPI) -> Iterator[None]:
    class _PlatformAdminService:
        def list_profiles(self) -> list[PlatformAdminProfileSummary]:
            return [
                PlatformAdminProfileSummary(
                    profile_id=98,
                    name="Tun Lahmajo",
                    profile_nick="tunlahmajo_1681123576",
                    subscription_status="expired",
                    subscription_expires_at=None,
                    default_user_id=101,
                    user_count=40,
                )
            ]

        def resolve_target(
            self,
            *,
            target_profile_id: int,
            target_profile_nick: str | None = None,
            target_user_id: int | None = None,
        ) -> Any:
            del target_profile_nick
            return type(
                "_Identity",
                (),
                {
                    "profile_nick": "tunlahmajo_1681123576",
                    "profile_id": target_profile_id,
                    "user_id": target_user_id or 101,
                },
            )()

    async def _override_admin_service() -> _PlatformAdminService:
        return _PlatformAdminService()

    app.dependency_overrides[_get_platform_admin_dependency] = _override_admin_service
    try:
        yield
    finally:
        app.dependency_overrides.pop(_get_platform_admin_dependency, None)


def _fake_run_smartrest_report(request: Any, *, profile_id: int) -> RunReportResponse:
    del profile_id
    metric_map = {
        ReportType.SALES_TOTAL: [ReportMetric(label="sales_total", value=12345.67)],
        ReportType.ORDER_COUNT: [ReportMetric(label="order_count", value=345.0)],
        ReportType.AVERAGE_CHECK: [ReportMetric(label="average_check", value=35.78)],
        ReportType.SALES_BY_SOURCE: [
            ReportMetric(label="in_store", value=10000.0),
            ReportMetric(label="takeaway", value=2345.67),
        ],
    }
    return RunReportResponse(
        result=ReportResult(
            report_id=request.report_id,
            filters=request.filters,
            metrics=metric_map[request.report_id],
        ),
        warnings=["smartrest_backend_live_data"],
    )


class _FakeLiveAnalyticsService:
    def get_total_metric(self, request: Any) -> TotalMetricResponse:
        previous = request.date_to < date(2026, 3, 10)
        value_map = {
            MetricName.SALES_TOTAL: Decimal("9000") if previous else Decimal("10000"),
            MetricName.ORDER_COUNT: Decimal("300") if previous else Decimal("345"),
            MetricName.AVERAGE_CHECK: Decimal("30") if previous else Decimal("35"),
        }
        return TotalMetricResponse(
            metric=request.metric,
            date_from=request.date_from,
            date_to=request.date_to,
            value=value_map.get(request.metric, Decimal("10000")),
            base_metrics={
                "sales_total": Decimal("10000"),
                "order_count": Decimal("345"),
                "day_count": Decimal("7"),
            },
            warnings=[],
        )

    def get_breakdown(self, request: Any) -> BreakdownResponse:
        items = [
            BreakdownItem(label="in_store", value=Decimal("10000")),
            BreakdownItem(label="takeaway", value=Decimal("2345.67")),
        ]
        return BreakdownResponse(
            metric=request.metric,
            dimension=request.dimension,
            date_from=request.date_from,
            date_to=request.date_to,
            items=items,
            total_value=Decimal("12345.67"),
            warnings=[],
        )

    def get_timeseries(self, request: Any) -> TimeseriesResponse:
        return TimeseriesResponse(
            metric=request.metric,
            dimension=request.dimension,
            date_from=request.date_from,
            date_to=request.date_to,
            points=[
                TimeseriesPoint(bucket=date(2026, 3, 10), value=Decimal("1000")),
                TimeseriesPoint(bucket=date(2026, 3, 11), value=Decimal("1100")),
            ],
            warnings=[],
        )


class _FakeBusinessToolsService:
    def get_item_performance(self, request: Any) -> ItemPerformanceResponse:
        return ItemPerformanceResponse(
            metric=request.metric or ItemPerformanceMetric.ITEM_REVENUE,
            date_from=request.date_from,
            date_to=request.date_to,
            ranking_mode=request.ranking_mode,
            items=[ItemPerformanceItem(menu_item_id=1, name="Lahmajo", value=Decimal("123"))],
            warnings=[],
        )

    def get_customer_summary(self, request: Any) -> CustomerSummaryResponse:
        return CustomerSummaryResponse(
            date_from=request.date_from,
            date_to=request.date_to,
            unique_clients=12,
            identified_order_count=48,
            total_order_count=60,
            average_orders_per_identified_client=Decimal("4"),
            warnings=[],
        )

    def get_receipt_summary(self, request: Any):
        from app.schemas.analysis import ReceiptSummaryResponse

        return ReceiptSummaryResponse(
            date_from=request.date_from,
            date_to=request.date_to,
            receipt_count=15,
            linked_order_count=14,
            status_counts={"30": 10, "50": 5},
            warnings=[],
        )


async def test_invalid_auth_token_returns_401(api_client: AsyncClient) -> None:
    payload = _request_payload("What were total sales 2026-03-01 to 2026-03-07?")
    payload["auth"]["token"] = "0" * 64

    response = await api_client.post("/agent/run", json=payload)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


async def test_platform_admin_profiles_returns_profiles(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/agent/admin/profiles",
        json={"admin_auth": _admin_auth_payload()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["profiles"][0]["profile_id"] == 98
    assert payload["profiles"][0]["default_user_id"] == 101


async def test_platform_admin_run_bypasses_subscription_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    api_client: AsyncClient,
) -> None:
    monkeypatch.setenv("SMARTREST_PLATFORM_ADMIN_BYPASS_SUBSCRIPTION", "true")
    get_settings.cache_clear()

    response = await api_client.post(
        "/agent/admin/run",
        json=_admin_run_payload("What were total sales 2026-03-01 to 2026-03-07?"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert "platform_admin_mode" in payload["warnings"]
    assert "platform_admin_subscription_bypass" in payload["warnings"]


async def test_platform_admin_run_checks_subscription_when_bypass_disabled(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    api_client: AsyncClient,
) -> None:
    monkeypatch.setenv("SMARTREST_PLATFORM_ADMIN_BYPASS_SUBSCRIPTION", "false")
    get_settings.cache_clear()

    class _DenyingSubscriptionService:
        def evaluate_access(self, _verified_identity: Any) -> SubscriptionAccessDecision:
            return SubscriptionAccessDecision(
                allowed=False,
                reason_code="subscription_expired",
                reason_message="AI agent subscription is inactive.",
            )

    async def _override_subscription_service() -> _DenyingSubscriptionService:
        return _DenyingSubscriptionService()

    app.dependency_overrides[_get_subscription_service] = _override_subscription_service
    try:
        response = await api_client.post(
            "/agent/admin/run",
            json=_admin_run_payload("What were total sales 2026-03-01 to 2026-03-07?"),
        )
    finally:
        app.dependency_overrides.pop(_get_subscription_service, None)

    assert response.status_code == 403
    assert response.json() == {"detail": "AI agent subscription is inactive."}


async def test_platform_admin_run_invalid_token_returns_401(
    api_client: AsyncClient,
) -> None:
    payload = _admin_run_payload("What were total sales 2026-03-01 to 2026-03-07?")
    payload["admin_auth"]["token"] = "0" * 64

    response = await api_client.post("/agent/admin/run", json=payload)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


async def test_mismatched_auth_and_scope_identity_returns_422(api_client: AsyncClient) -> None:
    payload = _request_payload("What were total sales 2026-03-01 to 2026-03-07?")
    payload["auth"]["profile_nick"] = "other"

    response = await api_client.post("/agent/run", json=payload)

    assert response.status_code == 422


async def test_inactive_subscription_returns_403(
    app: FastAPI,
    api_client: AsyncClient,
) -> None:
    class _DenyingSubscriptionService:
        def evaluate_access(self, _verified_identity: Any) -> SubscriptionAccessDecision:
            return SubscriptionAccessDecision(
                allowed=False,
                reason_code="subscription_expired",
                reason_message="AI agent subscription is inactive.",
            )

    async def _override_subscription_service() -> _DenyingSubscriptionService:
        return _DenyingSubscriptionService()

    app.dependency_overrides[_get_subscription_service] = _override_subscription_service
    try:
        response = await api_client.post(
            "/agent/run",
            json=_request_payload("What were total sales 2026-03-01 to 2026-03-07?"),
        )
    finally:
        app.dependency_overrides.pop(_get_subscription_service, None)

    assert response.status_code == 403
    assert response.json() == {"detail": "AI agent subscription is inactive."}


async def test_request_validation_error_returns_422(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/agent/run",
        json={
            "chat_id": "11111111-1111-1111-1111-111111111111",
            "user_question": "What were total sales?",
        },
    )

    assert response.status_code == 422


async def test_runtime_failure_returns_controlled_500(
    app: FastAPI,
    api_client: AsyncClient,
) -> None:
    class _FailingRuntime:
        def run(self, _request: AgentRunRequest, **_kwargs: Any) -> Any:
            raise AgentRuntimeExecutionError("boom")

        def run_as_platform_admin(
            self, _request: PlatformAdminRunRequest, **_kwargs: Any
        ) -> Any:
            raise AgentRuntimeExecutionError("boom")

    async def _override_dependency() -> _FailingRuntime:
        return _FailingRuntime()

    app.dependency_overrides[_get_runtime_service] = _override_dependency

    response = await api_client.post(
        "/agent/run",
        json=_request_payload("What were total sales 2026-03-01 to 2026-03-07?"),
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Agent runtime execution failed."}


async def test_health_endpoint_remains_available(api_client: AsyncClient) -> None:
    response = await api_client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
