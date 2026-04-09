from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.agent.formula_ast import evaluate_formula_ast
from app.agent.metric_registry import MetricType, get_metric_registry
from app.agent.tools.math_helpers import quantize_decimal
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
    TotalMetricRequest,
    TotalMetricResponse,
)
from app.smartrest.models import Order, get_sync_session_factory

_WEEKDAY_LABELS = {
    0: "sunday",
    1: "monday",
    2: "tuesday",
    3: "wednesday",
    4: "thursday",
    5: "friday",
    6: "saturday",
}


class LiveAnalyticsUnsupportedError(ValueError):
    pass


class LiveAnalyticsService:
    def __init__(
        self,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        self._session_factory = session_factory or get_sync_session_factory()

    def get_total_metric(self, request: TotalMetricRequest) -> TotalMetricResponse:
        scope = _require_scope(request.scope)
        base_metric_ids = _required_base_metrics(request.metric)
        with self._session_factory() as session:
            base_metrics = self._aggregate_base_metrics(
                session=session,
                scope=scope,
                date_from=request.date_from,
                date_to=request.date_to,
                metric_ids=base_metric_ids,
            )

        value = _materialize_metric_value(request.metric, base_metrics)
        response_base_metrics = _build_total_base_metrics_payload(
            metric=request.metric,
            base_metrics=base_metrics,
            date_from=request.date_from,
            date_to=request.date_to,
            metric_value=value,
        )
        return TotalMetricResponse(
            metric=request.metric,
            date_from=request.date_from,
            date_to=request.date_to,
            value=quantize_decimal(value),
            base_metrics=response_base_metrics,
            warnings=[],
        )

    def get_breakdown(self, request: BreakdownRequest) -> BreakdownResponse:
        scope = _require_scope(request.scope)
        bucket_expression, normalize_bucket = _dimension_expression(request.dimension)
        base_metric_ids = _required_base_metrics(request.metric)

        with self._session_factory() as session:
            rows = self._aggregate_grouped_base_metrics(
                session=session,
                scope=scope,
                date_from=request.date_from,
                date_to=request.date_to,
                metric_ids=base_metric_ids,
                bucket_expression=bucket_expression,
            )

        items: list[BreakdownItem] = []
        total_value = Decimal("0")
        for row in rows:
            row_base_metrics = _extract_metric_row(row=row, metric_ids=base_metric_ids)
            value = _materialize_metric_value(request.metric, row_base_metrics)
            total_value += value
            items.append(
                BreakdownItem(
                    label=normalize_bucket(row.bucket),
                    value=quantize_decimal(value),
                )
            )

        return BreakdownResponse(
            metric=request.metric,
            dimension=request.dimension,
            date_from=request.date_from,
            date_to=request.date_to,
            items=items,
            total_value=quantize_decimal(total_value),
            warnings=[],
        )

    def get_timeseries(self, request: TimeseriesRequest) -> TimeseriesResponse:
        scope = _require_scope(request.scope)
        if request.dimension is not DimensionName.DAY:
            raise LiveAnalyticsUnsupportedError(
                "Live timeseries currently supports day dimension only."
            )

        base_metric_ids = _required_base_metrics(request.metric)
        with self._session_factory() as session:
            rows = self._aggregate_grouped_base_metrics(
                session=session,
                scope=scope,
                date_from=request.date_from,
                date_to=request.date_to,
                metric_ids=base_metric_ids,
                bucket_expression=func.date(Order.order_create_date),
            )

        points_by_day: dict[date, Decimal] = {}
        for row in rows:
            bucket = _coerce_bucket_date(row.bucket)
            row_base_metrics = _extract_metric_row(row=row, metric_ids=base_metric_ids)
            points_by_day[bucket] = quantize_decimal(
                _materialize_metric_value(request.metric, row_base_metrics)
            )

        zero_base_metrics = {metric_id: Decimal("0") for metric_id in base_metric_ids}
        zero_value = quantize_decimal(_materialize_metric_value(request.metric, zero_base_metrics))
        points = [
            TimeseriesPoint(
                bucket=day,
                value=points_by_day.get(day, zero_value),
            )
            for day in _daterange(request.date_from, request.date_to)
        ]
        return TimeseriesResponse(
            metric=request.metric,
            dimension=request.dimension,
            date_from=request.date_from,
            date_to=request.date_to,
            points=points,
            warnings=[],
        )

    def _aggregate_base_metrics(
        self,
        *,
        session: Session,
        scope: RetrievalScope,
        date_from: date,
        date_to: date,
        metric_ids: tuple[str, ...],
    ) -> dict[str, Decimal]:
        statement = self._base_statement(
            scope=scope,
            date_from=date_from,
            date_to=date_to,
            metric_ids=metric_ids,
        )
        row = session.execute(statement).one()
        return {
            metric_id: _decimal_value(getattr(row, metric_id))
            for metric_id in metric_ids
        }

    def _aggregate_grouped_base_metrics(
        self,
        *,
        session: Session,
        scope: RetrievalScope,
        date_from: date,
        date_to: date,
        metric_ids: tuple[str, ...],
        bucket_expression: Any,
    ) -> list[Any]:
        statement = self._base_statement(
            scope=scope,
            date_from=date_from,
            date_to=date_to,
            metric_ids=metric_ids,
            bucket_expression=bucket_expression,
        )
        return list(session.execute(statement))

    def _base_statement(
        self,
        *,
        scope: RetrievalScope,
        date_from: date,
        date_to: date,
        metric_ids: tuple[str, ...],
        bucket_expression: Any | None = None,
    ):
        if scope.source is not None:
            raise LiveAnalyticsUnsupportedError(
                "Source-scoped live analytics are not supported yet."
            )

        metric_columns = [
            _base_metric_expression(metric_id).label(metric_id)
            for metric_id in metric_ids
        ]

        if bucket_expression is None:
            statement = select(*metric_columns)
        else:
            statement = select(bucket_expression.label("bucket"), *metric_columns).group_by(
                bucket_expression
            ).order_by(bucket_expression)

        statement = statement.where(Order.profile_id == scope.profile_id)
        statement = statement.where(func.date(Order.order_create_date) >= date_from)
        statement = statement.where(func.date(Order.order_create_date) <= date_to)
        if scope.branch_ids:
            statement = statement.where(Order.branch_id.in_(scope.branch_ids))
        return statement


def _require_scope(scope: RetrievalScope | None) -> RetrievalScope:
    if scope is None:
        raise LiveAnalyticsUnsupportedError("Live analytics require retrieval scope.")
    return scope


def _required_base_metrics(metric: MetricName) -> tuple[str, ...]:
    metric_definition = get_metric_registry().get(metric.value)
    if metric_definition is None:
        raise LiveAnalyticsUnsupportedError(f"Unknown metric: {metric.value}")

    metric_ids: tuple[str, ...]
    if metric_definition.metric_type is MetricType.BASE:
        metric_ids = (metric.value,)
    else:
        metric_ids = tuple(metric_definition.dependencies)

    unsupported_metrics = [
        metric_id for metric_id in metric_ids if metric_id not in _SUPPORTED_BASE_METRICS
    ]
    if unsupported_metrics:
        joined = ", ".join(sorted(unsupported_metrics))
        raise LiveAnalyticsUnsupportedError(
            f"Live analytics do not support metric dependencies yet: {joined}"
        )
    return metric_ids


_SUPPORTED_BASE_METRICS = {
    "sales_total",
    "order_count",
    "completed_order_count",
    "discount_amount",
    "delivery_order_count",
    "dine_in_order_count",
}


def _base_metric_expression(metric_id: str):
    if metric_id == "sales_total":
        return func.coalesce(
            func.sum(func.coalesce(Order.final_total, Order.total_price, 0)),
            0,
        )
    if metric_id in {"order_count", "completed_order_count"}:
        return func.count(Order.id)
    if metric_id == "discount_amount":
        return func.coalesce(func.sum(func.coalesce(Order.discounted_amount, 0)), 0)
    if metric_id == "delivery_order_count":
        return func.coalesce(
            func.sum(case((Order.is_delivery.is_(True), 1), else_=0)),
            0,
        )
    if metric_id == "dine_in_order_count":
        return func.coalesce(
            func.sum(case((Order.is_delivery.is_(True), 0), else_=1)),
            0,
        )
    raise LiveAnalyticsUnsupportedError(f"Unsupported live base metric: {metric_id}")


def _materialize_metric_value(metric: MetricName, base_metrics: dict[str, Decimal]) -> Decimal:
    metric_definition = get_metric_registry().get(metric.value)
    if metric_definition is None:
        raise LiveAnalyticsUnsupportedError(f"Unknown metric: {metric.value}")

    if metric_definition.metric_type is MetricType.BASE:
        value = base_metrics.get(metric.value)
        if value is None:
            raise LiveAnalyticsUnsupportedError(f"Missing base metric value for: {metric.value}")
        return value

    if metric_definition.formula_ast is None:
        raise LiveAnalyticsUnsupportedError(
            f"Derived metric is missing formula_ast: {metric.value}"
        )

    value, _warnings = evaluate_formula_ast(
        ast=metric_definition.formula_ast,
        base_metrics=base_metrics,
    )
    if value is None:
        if all(
            base_metrics.get(metric_id, Decimal("0")) == 0
            for metric_id in metric_definition.dependencies
        ):
            return Decimal("0")
        raise LiveAnalyticsUnsupportedError(
            f"Unable to evaluate live derived metric: {metric.value}"
        )
    return value


def _build_total_base_metrics_payload(
    *,
    metric: MetricName,
    base_metrics: dict[str, Decimal],
    date_from: date,
    date_to: date,
    metric_value: Decimal,
) -> dict[str, Decimal]:
    payload = {
        metric.value: quantize_decimal(metric_value),
        "day_count": Decimal((date_to - date_from).days + 1),
    }
    metric_definition = get_metric_registry().get(metric.value)
    if metric_definition is not None:
        for dependency in metric_definition.dependencies:
            if dependency in base_metrics:
                payload[dependency] = quantize_decimal(base_metrics[dependency])
    return payload


def _extract_metric_row(*, row: Any, metric_ids: tuple[str, ...]) -> dict[str, Decimal]:
    return {
        metric_id: _decimal_value(getattr(row, metric_id))
        for metric_id in metric_ids
    }


def _dimension_expression(
    dimension: DimensionName,
) -> tuple[Any, Callable[[Any], str]]:
    if dimension is DimensionName.DAY:
        return (
            func.date(Order.order_create_date),
            lambda value: _coerce_bucket_date(value).isoformat(),
        )
    if dimension is DimensionName.HOUR:
        return func.extract("hour", Order.order_create_date), _normalize_hour_bucket
    if dimension is DimensionName.WEEKDAY:
        return func.extract("dow", Order.order_create_date), _normalize_weekday_bucket
    if dimension is DimensionName.BRANCH:
        return Order.branch_id, _normalize_branch_bucket
    if dimension is DimensionName.CASHIER:
        return Order.profile_staff_id, _normalize_cashier_bucket
    raise LiveAnalyticsUnsupportedError(
        f"Live breakdown does not support dimension: {dimension.value}"
    )


def _normalize_hour_bucket(value: Any) -> str:
    if value is None:
        return "unknown_hour"
    return f"{int(value):02d}"


def _normalize_weekday_bucket(value: Any) -> str:
    if value is None:
        return "unknown_weekday"
    return _WEEKDAY_LABELS.get(int(value), f"weekday_{int(value)}")


def _normalize_branch_bucket(value: Any) -> str:
    if value is None:
        return "branch_unknown"
    return f"branch_{int(value)}"


def _normalize_cashier_bucket(value: Any) -> str:
    if value is None:
        return "cashier_unknown"
    return f"cashier_{int(value)}"


def _coerce_bucket_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise LiveAnalyticsUnsupportedError(f"Unsupported date bucket value: {value!r}")


def _decimal_value(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _daterange(start: date, end: date) -> Iterator[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


@lru_cache(maxsize=1)
def get_live_analytics_service() -> LiveAnalyticsService:
    return LiveAnalyticsService()
