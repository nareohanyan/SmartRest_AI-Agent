from __future__ import annotations

from app.agent.services.live_analytics import get_live_analytics_service
from app.core.config import get_settings
from app.core.runtime_policy import require_strict_backend_mode
from app.schemas.analysis import (
    BreakdownRequest,
    BreakdownResponse,
    TimeseriesRequest,
    TimeseriesResponse,
    TotalMetricRequest,
    TotalMetricResponse,
)


def fetch_total_metric_tool(request: TotalMetricRequest) -> TotalMetricResponse:
    _require_runtime_policy()
    if request.scope is None:
        raise ValueError("SmartRest retrieval requires retrieval scope.")
    return get_live_analytics_service().get_total_metric(request)


def fetch_breakdown_tool(request: BreakdownRequest) -> BreakdownResponse:
    _require_runtime_policy()
    if request.scope is None:
        raise ValueError("SmartRest retrieval requires retrieval scope.")
    return get_live_analytics_service().get_breakdown(request)


def fetch_timeseries_tool(request: TimeseriesRequest) -> TimeseriesResponse:
    _require_runtime_policy()
    if request.scope is None:
        raise ValueError("SmartRest retrieval requires retrieval scope.")
    return get_live_analytics_service().get_timeseries(request)


def _require_runtime_policy() -> None:
    settings = get_settings()
    require_strict_backend_mode(
        settings=settings,
        field_name="analytics_backend_mode",
        actual_mode=settings.analytics_backend_mode,
    )
