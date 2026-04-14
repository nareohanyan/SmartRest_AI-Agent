from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any

from app.agent.report_tools import resolve_scope_tool, run_report_tool
from app.agent.tools.analytics import (
    attach_breakdown_share_tool,
    compute_scalar_metrics_tool,
    moving_average_tool,
    trend_slope_tool,
)
from app.agent.tools.business_insights import (
    fetch_customer_summary_tool,
    fetch_item_performance_tool,
    fetch_receipt_summary_tool,
)
from app.agent.tools.ranking import bottom_k_tool, top_k_tool
from app.agent.tools.retrieval import (
    fetch_breakdown_tool,
    fetch_timeseries_tool,
    fetch_total_metric_tool,
)
from app.schemas.analysis import (
    BreakdownRequest,
    BreakdownResponse,
    CustomerSummaryRequest,
    ItemPerformanceRequest,
    MovingAverageRequest,
    RankItemsRequest,
    ReceiptSummaryRequest,
    TimeseriesRequest,
    TotalMetricRequest,
    TrendSlopeRequest,
)
from app.schemas.calculations import ComputeMetricsRequest
from app.schemas.tools import ResolveScopeRequest, RunReportRequest


class ToolId(str, Enum):
    RESOLVE_SCOPE = "resolve_scope"
    RUN_REPORT = "run_report"
    COMPUTE_SCALAR_METRICS = "compute_scalar_metrics"
    FETCH_TOTAL_METRIC = "fetch_total_metric"
    FETCH_BREAKDOWN = "fetch_breakdown"
    FETCH_TIMESERIES = "fetch_timeseries"
    FETCH_ITEM_PERFORMANCE = "fetch_item_performance"
    FETCH_CUSTOMER_SUMMARY = "fetch_customer_summary"
    FETCH_RECEIPT_SUMMARY = "fetch_receipt_summary"
    ATTACH_BREAKDOWN_SHARE = "attach_breakdown_share"
    TOP_K = "top_k"
    BOTTOM_K = "bottom_k"
    MOVING_AVERAGE = "moving_average"
    TREND_SLOPE = "trend_slope"


@dataclass(frozen=True)
class ToolSpec:
    tool_id: ToolId
    request_type: type[Any]
    handler: Any
    description: str


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec]) -> None:
        self._specs: dict[ToolId, ToolSpec] = {spec.tool_id: spec for spec in specs}

    def invoke(self, tool_id: ToolId | str, request: Any) -> Any:
        selected_tool_id = _coerce_tool_id(tool_id)
        spec = self._specs.get(selected_tool_id)
        if spec is None:
            raise KeyError(f"Unregistered tool: {selected_tool_id}")
        if not isinstance(request, spec.request_type):
            raise TypeError(
                f"Invalid request type for `{selected_tool_id.value}`: "
                f"expected {spec.request_type.__name__}, got {type(request).__name__}."
            )
        return spec.handler(request)

    def list_specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._specs.values())


def _coerce_tool_id(tool_id: ToolId | str) -> ToolId:
    if isinstance(tool_id, ToolId):
        return tool_id
    try:
        return ToolId(tool_id)
    except ValueError as exc:
        raise KeyError(f"Unregistered tool: {tool_id}") from exc


def _build_default_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            tool_id=ToolId.RESOLVE_SCOPE,
            request_type=ResolveScopeRequest,
            handler=resolve_scope_tool,
            description="Resolve user scope and allowed reports.",
        ),
        ToolSpec(
            tool_id=ToolId.RUN_REPORT,
            request_type=RunReportRequest,
            handler=run_report_tool,
            description="Run report request via backend adapter.",
        ),
        ToolSpec(
            tool_id=ToolId.COMPUTE_SCALAR_METRICS,
            request_type=ComputeMetricsRequest,
            handler=compute_scalar_metrics_tool,
            description="Compute deterministic derived scalar metrics.",
        ),
        ToolSpec(
            tool_id=ToolId.FETCH_TOTAL_METRIC,
            request_type=TotalMetricRequest,
            handler=fetch_total_metric_tool,
            description="Fetch SmartRest total metric for a time range.",
        ),
        ToolSpec(
            tool_id=ToolId.FETCH_BREAKDOWN,
            request_type=BreakdownRequest,
            handler=fetch_breakdown_tool,
            description="Fetch SmartRest metric breakdown for a time range.",
        ),
        ToolSpec(
            tool_id=ToolId.FETCH_TIMESERIES,
            request_type=TimeseriesRequest,
            handler=fetch_timeseries_tool,
            description="Fetch SmartRest timeseries metric points.",
        ),
        ToolSpec(
            tool_id=ToolId.FETCH_ITEM_PERFORMANCE,
            request_type=ItemPerformanceRequest,
            handler=fetch_item_performance_tool,
            description="Fetch ranked menu-item performance from SmartRest DB.",
        ),
        ToolSpec(
            tool_id=ToolId.FETCH_CUSTOMER_SUMMARY,
            request_type=CustomerSummaryRequest,
            handler=fetch_customer_summary_tool,
            description="Fetch customer summary metrics from SmartRest DB.",
        ),
        ToolSpec(
            tool_id=ToolId.FETCH_RECEIPT_SUMMARY,
            request_type=ReceiptSummaryRequest,
            handler=fetch_receipt_summary_tool,
            description="Fetch fiscal receipt summary metrics from SmartRest DB.",
        ),
        ToolSpec(
            tool_id=ToolId.ATTACH_BREAKDOWN_SHARE,
            request_type=BreakdownResponse,
            handler=attach_breakdown_share_tool,
            description="Attach share percentages to breakdown items.",
        ),
        ToolSpec(
            tool_id=ToolId.TOP_K,
            request_type=RankItemsRequest,
            handler=top_k_tool,
            description="Return top-k ranked items.",
        ),
        ToolSpec(
            tool_id=ToolId.BOTTOM_K,
            request_type=RankItemsRequest,
            handler=bottom_k_tool,
            description="Return bottom-k ranked items.",
        ),
        ToolSpec(
            tool_id=ToolId.MOVING_AVERAGE,
            request_type=MovingAverageRequest,
            handler=moving_average_tool,
            description="Compute moving average points.",
        ),
        ToolSpec(
            tool_id=ToolId.TREND_SLOPE,
            request_type=TrendSlopeRequest,
            handler=trend_slope_tool,
            description="Compute linear trend slope and direction.",
        ),
    ]


@lru_cache(maxsize=1)
def get_tool_registry() -> ToolRegistry:
    return ToolRegistry(_build_default_specs())


__all__ = [
    "ToolId",
    "ToolRegistry",
    "ToolSpec",
    "get_tool_registry",
]
