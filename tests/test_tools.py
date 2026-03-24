from __future__ import annotations

from datetime import date

import pytest

from app.agent.tool_registry import ToolId, get_tool_registry
from app.schemas.analysis import MetricName, ToolWarningCode, TotalMetricRequest
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
