from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.agent.formula_ast import evaluate_formula_ast
from app.agent.metric_registry import MetricType, get_metric_registry
from app.agent.services.live_analytics import get_live_analytics_service
from app.agent.tools.math_helpers import quantize_decimal
from app.core.config import get_settings
from app.schemas.analysis import (
    BreakdownItem,
    BreakdownRequest,
    BreakdownResponse,
    DimensionName,
    MetricName,
    TimeseriesPoint,
    TimeseriesRequest,
    TimeseriesResponse,
    ToolWarningCode,
    TotalMetricRequest,
    TotalMetricResponse,
)

_DIMENSION_BUCKET_WEIGHTS: dict[DimensionName, tuple[tuple[str, Decimal], ...]] = {
    DimensionName.SOURCE: (
        ("in_store", Decimal("0.24")),
        ("takeaway", Decimal("0.18")),
        ("glovo", Decimal("0.27")),
        ("wolt", Decimal("0.19")),
        ("yandex", Decimal("0.12")),
    ),
    DimensionName.BRANCH: (
        ("branch_1", Decimal("0.28")),
        ("branch_2", Decimal("0.24")),
        ("branch_3", Decimal("0.19")),
        ("branch_4", Decimal("0.17")),
        ("branch_5", Decimal("0.12")),
    ),
    DimensionName.DAY: (
        ("monday", Decimal("0.12")),
        ("tuesday", Decimal("0.13")),
        ("wednesday", Decimal("0.13")),
        ("thursday", Decimal("0.14")),
        ("friday", Decimal("0.16")),
        ("saturday", Decimal("0.17")),
        ("sunday", Decimal("0.15")),
    ),
    DimensionName.HOUR: (
        ("08", Decimal("0.06")),
        ("10", Decimal("0.10")),
        ("12", Decimal("0.18")),
        ("14", Decimal("0.17")),
        ("16", Decimal("0.12")),
        ("18", Decimal("0.19")),
        ("20", Decimal("0.18")),
    ),
    DimensionName.WEEKDAY: (
        ("weekday", Decimal("0.74")),
        ("weekend", Decimal("0.26")),
    ),
    DimensionName.PAYMENT_METHOD: (
        ("cash", Decimal("0.22")),
        ("card", Decimal("0.58")),
        ("qr", Decimal("0.08")),
        ("online_card", Decimal("0.12")),
    ),
    DimensionName.CATEGORY: (
        ("food", Decimal("0.52")),
        ("drinks", Decimal("0.21")),
        ("desserts", Decimal("0.13")),
        ("other", Decimal("0.14")),
    ),
    DimensionName.CASHIER: (
        ("cashier_1", Decimal("0.31")),
        ("cashier_2", Decimal("0.27")),
        ("cashier_3", Decimal("0.24")),
        ("cashier_4", Decimal("0.18")),
    ),
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


def _daily_base_metrics(day_index: int) -> dict[str, Decimal]:
    sales_total = _daily_sales_total(day_index)
    completed_order_count = _daily_order_count(day_index)
    canceled_order_count = (
        Decimal("2")
        + (Decimal(day_index % 6) * Decimal("0.3"))
        + (Decimal(day_index // 5) * Decimal("0.1"))
    )
    delivery_order_count = completed_order_count * Decimal("0.46")
    dine_in_order_count = completed_order_count * Decimal("0.34")
    refund_amount = sales_total * Decimal("0.03") + (Decimal(day_index % 4) * Decimal("0.8"))
    discount_amount = sales_total * Decimal("0.11") + (Decimal(day_index % 5) * Decimal("1.1"))

    return {
        "sales_total": sales_total,
        "order_count": completed_order_count,
        "completed_order_count": completed_order_count,
        "canceled_order_count": canceled_order_count,
        "refund_amount": refund_amount,
        "discount_amount": discount_amount,
        "delivery_order_count": delivery_order_count,
        "dine_in_order_count": dine_in_order_count,
    }


def _metric_value_from_base(metric: MetricName, base_metrics: dict[str, Decimal]) -> Decimal:
    metric_definition = get_metric_registry().get(metric.value)
    if metric_definition is None:
        raise ValueError(f"unknown metric in registry: {metric.value}")

    if metric_definition.metric_type is MetricType.BASE:
        value = base_metrics.get(metric.value)
        if value is None:
            raise ValueError(f"missing base metric value for: {metric.value}")
        return value

    if metric_definition.formula_ast is None:
        raise ValueError(f"derived metric is missing formula_ast: {metric.value}")
    value, _warnings = evaluate_formula_ast(
        ast=metric_definition.formula_ast,
        base_metrics=base_metrics,
    )
    if value is None:
        raise ValueError(f"unable to evaluate derived metric: {metric.value}")
    return value


def _metric_value_for_day(metric: MetricName, day_index: int) -> Decimal:
    base_metrics = _daily_base_metrics(day_index)
    return _metric_value_from_base(metric, base_metrics)


def fetch_total_metric_tool(request: TotalMetricRequest) -> TotalMetricResponse:
    if request.scope is not None and _use_live_analytics():
        try:
            return get_live_analytics_service().get_total_metric(request)
        except Exception:
            if _analytics_backend_mode() == "db_strict":
                raise

    aggregated_base_metrics: dict[str, Decimal] = {
        "sales_total": Decimal("0"),
        "order_count": Decimal("0"),
        "completed_order_count": Decimal("0"),
        "canceled_order_count": Decimal("0"),
        "refund_amount": Decimal("0"),
        "discount_amount": Decimal("0"),
        "delivery_order_count": Decimal("0"),
        "dine_in_order_count": Decimal("0"),
    }
    day_count_int = 0
    for index, _day in enumerate(_daterange(request.date_from, request.date_to)):
        daily_base_metrics = _daily_base_metrics(index)
        for metric_id, value in daily_base_metrics.items():
            aggregated_base_metrics[metric_id] += value
        day_count_int += 1

    total_value = _metric_value_from_base(request.metric, aggregated_base_metrics)

    day_count = Decimal(day_count_int)
    warnings = [ToolWarningCode.SYNTHETIC_DATA]
    if day_count_int == 1:
        warnings.append(ToolWarningCode.SINGLE_DAY_WINDOW)
    if day_count_int > 30:
        warnings.append(ToolWarningCode.LARGE_DATE_RANGE_SYNTHETIC)

    base_metrics = {
        request.metric.value: quantize_decimal(total_value),
        "day_count": day_count,
    }
    metric_definition = get_metric_registry().get(request.metric.value)
    if metric_definition is not None:
        for dependency in metric_definition.dependencies:
            if dependency in aggregated_base_metrics:
                base_metrics[dependency] = quantize_decimal(aggregated_base_metrics[dependency])
    return TotalMetricResponse(
        metric=request.metric,
        date_from=request.date_from,
        date_to=request.date_to,
        value=quantize_decimal(total_value),
        base_metrics=base_metrics,
        warnings=warnings,
    )


def fetch_breakdown_tool(request: BreakdownRequest) -> BreakdownResponse:
    if request.scope is not None and _use_live_analytics():
        try:
            return get_live_analytics_service().get_breakdown(request)
        except Exception:
            if _analytics_backend_mode() == "db_strict":
                raise

    bucket_weights = _DIMENSION_BUCKET_WEIGHTS.get(request.dimension)
    if bucket_weights is None:
        raise ValueError(f"unsupported dimension: {request.dimension}")

    dimension_totals = {label: Decimal("0") for label, _weight in bucket_weights}
    for index, _day in enumerate(_daterange(request.date_from, request.date_to)):
        metric_value = _metric_value_for_day(request.metric, index)
        for bucket_index, (label, weight) in enumerate(bucket_weights):
            day_adjustment = Decimal(bucket_index) * Decimal("0.005")
            dimension_totals[label] += metric_value * (weight + day_adjustment)

    total_value = sum(dimension_totals.values(), Decimal("0"))
    items = [
        BreakdownItem(label=label, value=quantize_decimal(value))
        for label, value in dimension_totals.items()
    ]
    return BreakdownResponse(
        metric=request.metric,
        dimension=request.dimension,
        date_from=request.date_from,
        date_to=request.date_to,
        items=items,
        total_value=quantize_decimal(total_value),
        warnings=[ToolWarningCode.SYNTHETIC_DATA],
    )


def fetch_timeseries_tool(request: TimeseriesRequest) -> TimeseriesResponse:
    if request.scope is not None and _use_live_analytics():
        try:
            return get_live_analytics_service().get_timeseries(request)
        except Exception:
            if _analytics_backend_mode() == "db_strict":
                raise

    if request.dimension is not DimensionName.DAY:
        raise ValueError("demo timeseries retrieval currently supports day dimension only")

    points = [
        TimeseriesPoint(
            bucket=day,
            value=quantize_decimal(_metric_value_for_day(request.metric, index)),
        )
        for index, day in enumerate(_daterange(request.date_from, request.date_to))
    ]
    warnings = [ToolWarningCode.SYNTHETIC_DATA]
    if len(points) < 2:
        warnings.append(ToolWarningCode.INSUFFICIENT_POINTS)
    return TimeseriesResponse(
        metric=request.metric,
        dimension=request.dimension,
        date_from=request.date_from,
        date_to=request.date_to,
        points=points,
        warnings=warnings,
    )


def _analytics_backend_mode() -> str:
    return getattr(get_settings(), "analytics_backend_mode", "mock")


def _use_live_analytics() -> bool:
    return _analytics_backend_mode() != "mock"
