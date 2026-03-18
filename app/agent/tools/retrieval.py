"""Deterministic retrieval tools for demo-friendly dynamic planning.

This module simulates a thin, typed retrieval layer over SmartRest business
metrics. In the demo version it generates stable synthetic data from the date
range, which makes Postman tests predictable while preserving the shape of a
future real data adapter.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.agent.tools.math_helpers import quantize_decimal
from app.schemas.analysis import (
    BreakdownItem,
    BreakdownRequest,
    BreakdownResponse,
    DimensionName,
    MetricName,
    TimeseriesPoint,
    TimeseriesRequest,
    TimeseriesResponse,
    TotalMetricRequest,
    TotalMetricResponse,
)

_SOURCE_WEIGHTS: dict[str, Decimal] = {
    "glovo": Decimal("0.34"),
    "wolt": Decimal("0.27"),
    "direct": Decimal("0.21"),
    "in_store": Decimal("0.18"),
}


def _daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _daily_sales_total(day_index: int) -> Decimal:
    weekday_modifiers = [
        Decimal("0"),
        Decimal("18"),
        Decimal("42"),
        Decimal("25"),
        Decimal("60"),
        Decimal("110"),
        Decimal("85"),
    ]
    weekday_adjustment = weekday_modifiers[day_index % 7]
    return Decimal("900") + (Decimal(day_index) * Decimal("37")) + weekday_adjustment


def _daily_order_count(day_index: int) -> Decimal:
    weekday_modifiers = [
        Decimal("0"),
        Decimal("1"),
        Decimal("3"),
        Decimal("2"),
        Decimal("4"),
        Decimal("7"),
        Decimal("5"),
    ]
    weekday_adjustment = weekday_modifiers[day_index % 7]
    return Decimal("36") + (Decimal(day_index) * Decimal("2")) + weekday_adjustment


def _metric_value_for_day(metric: MetricName, day_index: int) -> Decimal:
    sales_total = _daily_sales_total(day_index)
    order_count = _daily_order_count(day_index)

    if metric is MetricName.SALES_TOTAL:
        return sales_total
    if metric is MetricName.ORDER_COUNT:
        return order_count
    if metric is MetricName.AVERAGE_CHECK:
        return sales_total / order_count
    raise ValueError(f"unsupported metric: {metric}")


def fetch_total_metric_tool(request: TotalMetricRequest) -> TotalMetricResponse:
    sales_total_sum = Decimal("0")
    order_count_sum = Decimal("0")
    day_count_int = 0
    for index, _day in enumerate(_daterange(request.date_from, request.date_to)):
        sales_total_sum += _daily_sales_total(index)
        order_count_sum += _daily_order_count(index)
        day_count_int += 1

    if request.metric is MetricName.SALES_TOTAL:
        total_value = sales_total_sum
    elif request.metric is MetricName.ORDER_COUNT:
        total_value = order_count_sum
    elif request.metric is MetricName.AVERAGE_CHECK:
        total_value = sales_total_sum / order_count_sum
    else:
        raise ValueError(f"unsupported metric: {request.metric}")

    day_count = Decimal(day_count_int)

    base_metrics = {
        request.metric.value: quantize_decimal(total_value),
        "day_count": day_count,
    }
    return TotalMetricResponse(
        metric=request.metric,
        date_from=request.date_from,
        date_to=request.date_to,
        value=quantize_decimal(total_value),
        base_metrics=base_metrics,
    )


def fetch_breakdown_tool(request: BreakdownRequest) -> BreakdownResponse:
    if request.dimension is not DimensionName.SOURCE:
        raise ValueError("demo breakdown retrieval only supports source dimension")

    source_totals = {label: Decimal("0") for label in _SOURCE_WEIGHTS}
    for index, _day in enumerate(_daterange(request.date_from, request.date_to)):
        metric_value = _metric_value_for_day(request.metric, index)
        for source_index, (label, weight) in enumerate(_SOURCE_WEIGHTS.items()):
            day_adjustment = Decimal(source_index) * Decimal("0.01")
            source_totals[label] += metric_value * (weight + day_adjustment)

    total_value = sum(source_totals.values(), Decimal("0"))
    items = [
        BreakdownItem(label=label, value=quantize_decimal(value))
        for label, value in source_totals.items()
    ]
    return BreakdownResponse(
        metric=request.metric,
        dimension=request.dimension,
        date_from=request.date_from,
        date_to=request.date_to,
        items=items,
        total_value=quantize_decimal(total_value),
    )


def fetch_timeseries_tool(request: TimeseriesRequest) -> TimeseriesResponse:
    points = [
        TimeseriesPoint(
            bucket=day,
            value=quantize_decimal(_metric_value_for_day(request.metric, index)),
        )
        for index, day in enumerate(_daterange(request.date_from, request.date_to))
    ]
    return TimeseriesResponse(
        metric=request.metric,
        dimension=request.dimension,
        date_from=request.date_from,
        date_to=request.date_to,
        points=points,
    )
