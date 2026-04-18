from __future__ import annotations

import importlib
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.agent.tool_registry import ToolId, get_tool_registry
from app.agent.tools import business_insights as business_insights_tools
from app.agent.tools import retrieval as retrieval_tools
from app.core.runtime_policy import RuntimePolicyError
from app.schemas.analysis import (
    BreakdownItem,
    BreakdownRequest,
    BreakdownResponse,
    CustomerSummaryRequest,
    CustomerSummaryResponse,
    DimensionName,
    ItemPerformanceItem,
    ItemPerformanceMetric,
    ItemPerformanceRequest,
    ItemPerformanceResponse,
    MetricName,
    RankingMode,
    ReceiptSummaryRequest,
    ReceiptSummaryResponse,
    RetrievalScope,
    TimeseriesPoint,
    TimeseriesRequest,
    TimeseriesResponse,
    TotalMetricRequest,
    TotalMetricResponse,
)
from app.schemas.tools import ResolveScopeRequest


def _scope_request() -> ResolveScopeRequest:
    return ResolveScopeRequest(
        user_id=101,
        profile_id=201,
        profile_nick="nick",
        metadata={},
    )


def test_tool_registry_has_expected_approved_tool_set() -> None:
    registry = get_tool_registry()

    assert {spec.tool_id for spec in registry.list_specs()} == {
        ToolId.RESOLVE_SCOPE,
        ToolId.RUN_REPORT,
        ToolId.COMPUTE_SCALAR_METRICS,
        ToolId.FETCH_TOTAL_METRIC,
        ToolId.FETCH_BREAKDOWN,
        ToolId.FETCH_TIMESERIES,
        ToolId.FETCH_ITEM_PERFORMANCE,
        ToolId.FETCH_CUSTOMER_SUMMARY,
        ToolId.FETCH_RECEIPT_SUMMARY,
        ToolId.ATTACH_BREAKDOWN_SHARE,
        ToolId.TOP_K,
        ToolId.BOTTOM_K,
        ToolId.MOVING_AVERAGE,
        ToolId.TREND_SLOPE,
    }


def test_tool_registry_invokes_registered_tool_with_typed_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _LiveService:
        def get_total_metric(self, request: TotalMetricRequest) -> TotalMetricResponse:
            return TotalMetricResponse(
                metric=request.metric,
                date_from=request.date_from,
                date_to=request.date_to,
                value=Decimal("99"),
                base_metrics={"sales_total": Decimal("99"), "day_count": Decimal("7")},
                warnings=[],
            )

    monkeypatch.setattr(
        retrieval_tools,
        "get_settings",
        lambda: SimpleNamespace(analytics_backend_mode="db_strict"),
    )
    monkeypatch.setattr(retrieval_tools, "get_live_analytics_service", lambda: _LiveService())
    get_tool_registry.cache_clear()
    registry = get_tool_registry()

    response = registry.invoke(
        ToolId.FETCH_TOTAL_METRIC,
        TotalMetricRequest(
            metric=MetricName.SALES_TOTAL,
            date_from=date(2026, 3, 1),
            date_to=date(2026, 3, 7),
            scope=RetrievalScope(profile_id=98),
        ),
    )

    assert response.metric is MetricName.SALES_TOTAL
    assert response.warnings == []
    get_tool_registry.cache_clear()


def test_tool_registry_rejects_unregistered_tool() -> None:
    registry = get_tool_registry()

    with pytest.raises(KeyError, match="Unregistered tool"):
        registry.invoke("unknown_tool", _scope_request())


def test_tool_registry_rejects_wrong_request_type() -> None:
    registry = get_tool_registry()

    with pytest.raises(TypeError, match="Invalid request type"):
        registry.invoke(ToolId.FETCH_TOTAL_METRIC, _scope_request())


def test_fetch_total_metric_tool_uses_live_service_when_scope_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _LiveService:
        def get_total_metric(self, request: TotalMetricRequest) -> TotalMetricResponse:
            assert request.scope is not None
            assert request.scope.profile_id == 201
            return TotalMetricResponse(
                metric=request.metric,
                date_from=request.date_from,
                date_to=request.date_to,
                value=Decimal("42"),
                base_metrics={"sales_total": Decimal("42"), "day_count": Decimal("7")},
                warnings=[],
            )

    monkeypatch.setattr(
        retrieval_tools,
        "get_settings",
        lambda: SimpleNamespace(analytics_backend_mode="db_strict"),
    )
    monkeypatch.setattr(retrieval_tools, "get_live_analytics_service", lambda: _LiveService())

    response = retrieval_tools.fetch_total_metric_tool(
        TotalMetricRequest(
            metric=MetricName.SALES_TOTAL,
            date_from=date(2026, 3, 1),
            date_to=date(2026, 3, 7),
            scope=RetrievalScope(profile_id=201),
        )
    )

    assert response.value == Decimal("42")
    assert response.warnings == []


def test_fetch_breakdown_tool_uses_live_service_when_scope_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _LiveService:
        def get_breakdown(self, request: BreakdownRequest) -> BreakdownResponse:
            assert request.scope is not None
            return BreakdownResponse(
                metric=request.metric,
                dimension=request.dimension,
                date_from=request.date_from,
                date_to=request.date_to,
                items=[BreakdownItem(label="branch_1", value=Decimal("21"))],
                total_value=Decimal("21"),
                warnings=[],
            )

    monkeypatch.setattr(
        retrieval_tools,
        "get_settings",
        lambda: SimpleNamespace(analytics_backend_mode="db_strict"),
    )
    monkeypatch.setattr(retrieval_tools, "get_live_analytics_service", lambda: _LiveService())

    response = retrieval_tools.fetch_breakdown_tool(
        BreakdownRequest(
            metric=MetricName.SALES_TOTAL,
            dimension=DimensionName.BRANCH,
            date_from=date(2026, 3, 1),
            date_to=date(2026, 3, 7),
            scope=RetrievalScope(profile_id=201),
        )
    )

    assert response.items[0].label == "branch_1"
    assert response.warnings == []


def test_live_analytics_service_category_breakdown_uses_category_subquery() -> None:
    live_analytics_module = importlib.import_module("app.agent.services.live_analytics")

    class _FakeSession:
        def __enter__(self) -> _FakeSession:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            del exc_type, exc, tb

        def execute(self, statement: object) -> list[SimpleNamespace]:
            del statement
            return [SimpleNamespace(bucket="Khinkali", value=Decimal("7"))]

    service = live_analytics_module.LiveAnalyticsService(session_factory=lambda: _FakeSession())

    response = service.get_breakdown(
        BreakdownRequest(
            metric=MetricName.SALES_TOTAL,
            dimension=DimensionName.CATEGORY,
            date_from=date(2026, 3, 1),
            date_to=date(2026, 3, 7),
            scope=RetrievalScope(profile_id=201),
        )
    )

    assert response.items == [BreakdownItem(label="Khinkali", value=Decimal("7.00"))]
    assert response.total_value == Decimal("7.00")
    assert response.warnings == []


def test_fetch_timeseries_tool_uses_live_service_when_scope_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _LiveService:
        def get_timeseries(self, request: TimeseriesRequest) -> TimeseriesResponse:
            assert request.scope is not None
            return TimeseriesResponse(
                metric=request.metric,
                dimension=request.dimension,
                date_from=request.date_from,
                date_to=request.date_to,
                points=[TimeseriesPoint(bucket=date(2026, 3, 1), value=Decimal("5"))],
                warnings=[],
            )

    monkeypatch.setattr(
        retrieval_tools,
        "get_settings",
        lambda: SimpleNamespace(analytics_backend_mode="db_strict"),
    )
    monkeypatch.setattr(retrieval_tools, "get_live_analytics_service", lambda: _LiveService())

    response = retrieval_tools.fetch_timeseries_tool(
        TimeseriesRequest(
            metric=MetricName.SALES_TOTAL,
            date_from=date(2026, 3, 1),
            date_to=date(2026, 3, 7),
            dimension=DimensionName.DAY,
            scope=RetrievalScope(profile_id=201),
        )
    )

    assert response.points[0].value == Decimal("5")
    assert response.warnings == []


def test_fetch_item_performance_tool_uses_live_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _LiveService:
        def get_item_performance(
            self, request: ItemPerformanceRequest
        ) -> ItemPerformanceResponse:
            assert request.scope is not None
            return ItemPerformanceResponse(
                metric=request.metric,
                date_from=request.date_from,
                date_to=request.date_to,
                ranking_mode=request.ranking_mode,
                items=[
                    ItemPerformanceItem(
                        menu_item_id=11,
                        name="Lahmajo",
                        value=Decimal("321.50"),
                    )
                ],
                warnings=[],
            )

    monkeypatch.setattr(
        business_insights_tools,
        "get_settings",
        lambda: SimpleNamespace(analytics_backend_mode="db_strict"),
    )
    monkeypatch.setattr(
        business_insights_tools,
        "LiveBusinessToolsService",
        lambda: _LiveService(),
    )

    response = business_insights_tools.fetch_item_performance_tool(
        ItemPerformanceRequest(
            metric=ItemPerformanceMetric.ITEM_REVENUE,
            date_from=date(2026, 3, 1),
            date_to=date(2026, 3, 7),
            ranking_mode=RankingMode.TOP_K,
            scope=RetrievalScope(profile_id=201),
        )
    )

    assert response.items[0].name == "Lahmajo"
    assert response.warnings == []


def test_fetch_customer_summary_tool_uses_live_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _LiveService:
        def get_customer_summary(
            self, request: CustomerSummaryRequest
        ) -> CustomerSummaryResponse:
            assert request.scope is not None
            return CustomerSummaryResponse(
                date_from=request.date_from,
                date_to=request.date_to,
                unique_clients=12,
                identified_order_count=48,
                total_order_count=60,
                average_orders_per_identified_client=Decimal("4.00"),
                warnings=[],
            )

    monkeypatch.setattr(
        business_insights_tools,
        "get_settings",
        lambda: SimpleNamespace(analytics_backend_mode="db_strict"),
    )
    monkeypatch.setattr(
        business_insights_tools,
        "LiveBusinessToolsService",
        lambda: _LiveService(),
    )

    response = business_insights_tools.fetch_customer_summary_tool(
        CustomerSummaryRequest(
            date_from=date(2026, 3, 1),
            date_to=date(2026, 3, 7),
            scope=RetrievalScope(profile_id=201),
        )
    )

    assert response.unique_clients == 12
    assert response.average_orders_per_identified_client == Decimal("4.00")


def test_fetch_receipt_summary_tool_uses_live_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _LiveService:
        def get_receipt_summary(
            self, request: ReceiptSummaryRequest
        ) -> ReceiptSummaryResponse:
            assert request.scope is not None
            return ReceiptSummaryResponse(
                date_from=request.date_from,
                date_to=request.date_to,
                receipt_count=15,
                linked_order_count=14,
                status_counts={"30": 10, "50": 5},
                warnings=[],
            )

    monkeypatch.setattr(
        business_insights_tools,
        "get_settings",
        lambda: SimpleNamespace(analytics_backend_mode="db_strict"),
    )
    monkeypatch.setattr(
        business_insights_tools,
        "LiveBusinessToolsService",
        lambda: _LiveService(),
    )

    response = business_insights_tools.fetch_receipt_summary_tool(
        ReceiptSummaryRequest(
            date_from=date(2026, 3, 1),
            date_to=date(2026, 3, 7),
            scope=RetrievalScope(profile_id=201),
        )
    )

    assert response.receipt_count == 15
    assert response.status_counts["30"] == 10


def test_fetch_total_metric_strict_environment_rejects_mock_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        retrieval_tools,
        "get_settings",
        lambda: SimpleNamespace(app_env="staging", analytics_backend_mode="mock"),
    )

    with pytest.raises(RuntimePolicyError, match="analytics_backend_mode=db_strict"):
        retrieval_tools.fetch_total_metric_tool(
            TotalMetricRequest(
                metric=MetricName.SALES_TOTAL,
                date_from=date(2026, 3, 1),
                date_to=date(2026, 3, 7),
            )
        )


def test_fetch_item_performance_tool_rejects_mock_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        business_insights_tools,
        "get_settings",
        lambda: SimpleNamespace(app_env="staging", analytics_backend_mode="mock"),
    )

    with pytest.raises(RuntimePolicyError, match="analytics_backend_mode=db_strict"):
        business_insights_tools.fetch_item_performance_tool(
            ItemPerformanceRequest(
                metric=ItemPerformanceMetric.ITEM_REVENUE,
                date_from=date(2026, 3, 1),
                date_to=date(2026, 3, 7),
                scope=RetrievalScope(profile_id=201),
            )
        )
