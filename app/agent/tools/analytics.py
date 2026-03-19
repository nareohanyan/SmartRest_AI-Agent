from __future__ import annotations

from decimal import Decimal
from typing import Literal

from app.agent.calc_tools import compute_metrics_tool
from app.agent.tools.math_helpers import linear_regression_slope, quantize_decimal
from app.schemas.analysis import (
    BreakdownItem,
    BreakdownResponse,
    MovingAveragePoint,
    MovingAverageRequest,
    MovingAverageResponse,
    TimeseriesPoint,
    TrendSlopeRequest,
    TrendSlopeResponse,
)
from app.schemas.calculations import ComputeMetricsRequest, ComputeMetricsResponse


def compute_scalar_metrics_tool(request: ComputeMetricsRequest) -> ComputeMetricsResponse:
    """Forward to the existing typed calculation engine.

    This keeps the project centered on a single trusted scalar-math implementation,
    while allowing the planner to choose those calculations dynamically.
    """
    return compute_metrics_tool(request)


def attach_breakdown_share_tool(response: BreakdownResponse) -> BreakdownResponse:
    if response.total_value == 0:
        return response

    enriched_items = []
    for item in response.items:
        share = quantize_decimal((item.value / response.total_value) * Decimal("100"))
        enriched_items.append(
            BreakdownItem(label=item.label, value=item.value, share_percent=share)
        )

    return response.model_copy(update={"items": enriched_items})


def moving_average_tool(request: MovingAverageRequest) -> MovingAverageResponse:
    output: list[MovingAveragePoint] = []
    for index, point in enumerate(request.points):
        if index + 1 < request.window_size:
            output.append(MovingAveragePoint(bucket=point.bucket, value=None))
            continue

        window = request.points[index + 1 - request.window_size : index + 1]
        window_sum = sum((window_point.value for window_point in window), Decimal("0"))
        average = quantize_decimal(window_sum / Decimal(request.window_size))
        output.append(MovingAveragePoint(bucket=point.bucket, value=average))

    return MovingAverageResponse(points=output)


def trend_slope_tool(request: TrendSlopeRequest) -> TrendSlopeResponse:
    slope = quantize_decimal(
        linear_regression_slope([point.value for point in request.points]),
        precision=4,
    )
    direction: Literal["up", "down", "flat"]
    if slope > 0:
        direction = "up"
    elif slope < 0:
        direction = "down"
    else:
        direction = "flat"

    return TrendSlopeResponse(slope_per_day=slope, direction=direction)


def materialize_previous_period_metrics(
    current_metric_key: str,
    current_total: Decimal,
    previous_total: Decimal,
    day_count: Decimal,
) -> dict[str, Decimal]:
    """Helper for comparison plans.

    Produces a base-metric map that plugs directly into ComputeMetricsRequest.
    """
    return {
        current_metric_key: quantize_decimal(current_total),
        f"{current_metric_key}_previous": quantize_decimal(previous_total),
        "day_count": day_count,
    }


def materialize_timeseries_as_base_metrics(
    points: list[TimeseriesPoint],
    prefix: str,
) -> dict[str, Decimal]:
    return {
        f"{prefix}_{point.bucket.isoformat()}": point.value
        for point in points
    }
