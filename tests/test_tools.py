from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.agent.tool_registry import ToolId, get_tool_registry
from app.agent.tools import retrieval as retrieval_tools
from app.schemas.analysis import (
    BreakdownItem,
    BreakdownRequest,
    BreakdownResponse,
    DimensionName,
    MetricName,
    RetrievalScope,
    TimeseriesPoint,
    TimeseriesRequest,
    TimeseriesResponse,
    ToolWarningCode,
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
        ToolId.ATTACH_BREAKDOWN_SHARE,
        ToolId.TOP_K,
        ToolId.BOTTOM_K,
        ToolId.MOVING_AVERAGE,
        ToolId.TREND_SLOPE,
    }


def test_tool_registry_invokes_registered_tool_with_typed_request() -> None:
    registry = get_tool_registry()

    response = registry.invoke(
        ToolId.FETCH_TOTAL_METRIC,
        TotalMetricRequest(
            metric=MetricName.SALES_TOTAL,
            date_from=date(2026, 3, 1),
            date_to=date(2026, 3, 7),
        ),
    )

    assert response.metric is MetricName.SALES_TOTAL
    assert ToolWarningCode.SYNTHETIC_DATA in response.warnings


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
