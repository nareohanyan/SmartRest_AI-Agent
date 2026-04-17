from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from types import SimpleNamespace
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.agent.formula_ast import evaluate_formula_ast
from app.agent.live_capabilities import (
    LIVE_BASE_METRIC_IDS,
    LIVE_SPECIALIZED_BREAKDOWN_METRIC_IDS,
)
from app.agent.metric_registry import MetricType, get_metric_registry
from app.agent.services.smartrest_query_support import (
    apply_order_filters,
    sales_total_expression,
    source_bucket_expression,
)
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
from app.smartrest.models import (
    Cashbox,
    MenuGroup,
    MenuItem,
    Order,
    OrderContent,
    OrderPaymentHistory,
    get_sync_session_factory,
)

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
            if request.dimension in {DimensionName.PAYMENT_METHOD, DimensionName.CATEGORY}:
                rows = self._aggregate_specialized_grouped_base_metrics(
                    session=session,
                    scope=scope,
                    date_from=request.date_from,
                    date_to=request.date_to,
                    metric_ids=base_metric_ids,
                    dimension=request.dimension,
                )
            else:
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
        return {
            metric_id: self._aggregate_metric_total(
                session=session,
                scope=scope,
                date_from=date_from,
                date_to=date_to,
                metric_id=metric_id,
            )
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
        grouped_values_by_metric = {
            metric_id: self._aggregate_metric_grouped(
                session=session,
                scope=scope,
                date_from=date_from,
                date_to=date_to,
                metric_id=metric_id,
                bucket_expression=bucket_expression,
            )
            for metric_id in metric_ids
        }
        return _merge_grouped_metric_values(
            grouped_values_by_metric=grouped_values_by_metric,
            metric_ids=metric_ids,
        )

    def _aggregate_specialized_grouped_base_metrics(
        self,
        *,
        session: Session,
        scope: RetrievalScope,
        date_from: date,
        date_to: date,
        metric_ids: tuple[str, ...],
        dimension: DimensionName,
    ) -> list[Any]:
        grouped_values_by_metric = {
            metric_id: self._aggregate_specialized_grouped_metric(
                session=session,
                scope=scope,
                date_from=date_from,
                date_to=date_to,
                metric_id=metric_id,
                dimension=dimension,
            )
            for metric_id in metric_ids
        }
        return _merge_grouped_metric_values(
            grouped_values_by_metric=grouped_values_by_metric,
            metric_ids=metric_ids,
        )

    def _aggregate_metric_total(
        self,
        *,
        session: Session,
        scope: RetrievalScope,
        date_from: date,
        date_to: date,
        metric_id: str,
    ) -> Decimal:
        statement = _metric_total_statement(
            scope=scope,
            date_from=date_from,
            date_to=date_to,
            metric_id=metric_id,
        )
        return _decimal_value(session.execute(statement).scalar_one())

    def _aggregate_metric_grouped(
        self,
        *,
        session: Session,
        scope: RetrievalScope,
        date_from: date,
        date_to: date,
        metric_id: str,
        bucket_expression: Any,
    ) -> dict[Any, Decimal]:
        statement = _metric_grouped_statement(
            scope=scope,
            date_from=date_from,
            date_to=date_to,
            metric_id=metric_id,
            bucket_expression=bucket_expression,
        )
        return {row.bucket: _decimal_value(row.value) for row in session.execute(statement)}

    def _aggregate_specialized_grouped_metric(
        self,
        *,
        session: Session,
        scope: RetrievalScope,
        date_from: date,
        date_to: date,
        metric_id: str,
        dimension: DimensionName,
    ) -> dict[Any, Decimal]:
        statement = _specialized_grouped_metric_statement(
            scope=scope,
            date_from=date_from,
            date_to=date_to,
            metric_id=metric_id,
            dimension=dimension,
        )
        return {row.bucket: _decimal_value(row.value) for row in session.execute(statement)}


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
        metric_id for metric_id in metric_ids if metric_id not in LIVE_BASE_METRIC_IDS
    ]
    if unsupported_metrics:
        joined = ", ".join(sorted(unsupported_metrics))
        raise LiveAnalyticsUnsupportedError(
            f"Live analytics do not support metric dependencies yet: {joined}"
        )
    return metric_ids


def _base_metric_expression(metric_id: str):
    if metric_id == "sales_total":
        return sales_total_expression()
    if metric_id in {"order_count", "completed_order_count"}:
        return func.count(Order.id)
    if metric_id == "discounted_order_count":
        return func.coalesce(
            func.sum(case((func.coalesce(Order.discounted_amount, 0) > 0, 1), else_=0)),
            0,
        )
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


def _quantity_sold_expression() -> Any:
    return func.coalesce(
        func.sum(func.coalesce(OrderContent.profile_menu_item_count, 0)),
        0,
    )


def _metric_total_statement(
    *,
    scope: RetrievalScope,
    date_from: date,
    date_to: date,
    metric_id: str,
):
    if metric_id == "quantity_sold":
        statement = (
            select(_quantity_sold_expression().label("value"))
            .select_from(Order)
            .join(OrderContent, OrderContent.room_table_order_id == Order.id)
        )
    else:
        statement = select(_base_metric_expression(metric_id).label("value")).select_from(Order)

    return apply_order_filters(
        statement,
        profile_id=scope.profile_id,
        date_from=date_from,
        date_to=date_to,
        branch_ids=scope.branch_ids,
        source=scope.source,
    )


def _metric_grouped_statement(
    *,
    scope: RetrievalScope,
    date_from: date,
    date_to: date,
    metric_id: str,
    bucket_expression: Any,
):
    metric_expression = (
        _quantity_sold_expression()
        if metric_id == "quantity_sold"
        else _base_metric_expression(metric_id)
    )
    statement = select(
        bucket_expression.label("bucket"),
        metric_expression.label("value"),
    ).select_from(
        Order,
    )
    if metric_id == "quantity_sold":
        statement = statement.join(OrderContent, OrderContent.room_table_order_id == Order.id)
    statement = statement.group_by(bucket_expression).order_by(bucket_expression)
    return apply_order_filters(
        statement,
        profile_id=scope.profile_id,
        date_from=date_from,
        date_to=date_to,
        branch_ids=scope.branch_ids,
        source=scope.source,
    )


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
    if dimension is DimensionName.SOURCE:
        return source_bucket_expression(), _normalize_source_bucket
    if dimension is DimensionName.BRANCH:
        return Order.branch_id, _normalize_branch_bucket
    if dimension is DimensionName.CASHIER:
        return Order.profile_staff_id, _normalize_cashier_bucket
    if dimension is DimensionName.PAYMENT_METHOD:
        return _payment_method_bucket_expression(), _normalize_payment_method_bucket
    if dimension is DimensionName.CATEGORY:
        return _category_bucket_expression(), _normalize_category_bucket
    raise LiveAnalyticsUnsupportedError(
        f"Live breakdown does not support dimension: {dimension.value}"
    )


def _payment_method_bucket_expression() -> Any:
    normalized_name = func.lower(
        func.trim(func.coalesce(Cashbox.cashbox_name_en, Cashbox.cashbox_name, ""))
    )
    return case(
        (normalized_name.like("%idram%"), "idram"),
        (
            normalized_name.in_(("cash", "cache"))
            | normalized_name.like("cash %")
            | normalized_name.like("cache %"),
            "cash",
        ),
        (Cashbox.is_bank.is_(True), "card"),
        else_="other_payment_method",
    )


def _category_bucket_expression() -> Any:
    return func.coalesce(
        func.nullif(MenuGroup.title_en, ""),
        func.nullif(MenuGroup.title_ru, ""),
        func.nullif(MenuGroup.title, ""),
        func.concat("category_", MenuGroup.id),
        "unknown_category",
    )


def _normalize_hour_bucket(value: Any) -> str:
    if value is None:
        return "unknown_hour"
    return f"{int(value):02d}"


def _normalize_weekday_bucket(value: Any) -> str:
    if value is None:
        return "unknown_weekday"
    return _WEEKDAY_LABELS.get(int(value), f"weekday_{int(value)}")


def _normalize_source_bucket(value: Any) -> str:
    if value is None:
        return "unknown_source"
    return str(value)


def _normalize_branch_bucket(value: Any) -> str:
    if value is None:
        return "branch_unknown"
    return f"branch_{int(value)}"


def _normalize_cashier_bucket(value: Any) -> str:
    if value is None:
        return "cashier_unknown"
    return f"cashier_{int(value)}"


def _normalize_payment_method_bucket(value: Any) -> str:
    if value is None:
        return "unknown_payment_method"
    normalized = str(value).strip().lower().replace(" ", "_")
    if normalized in {"cache", "cash"}:
        return "cash"
    if normalized == "idram":
        return "idram"
    if normalized in {"card", "bank"}:
        return "card"
    return normalized


def _normalize_category_bucket(value: Any) -> str:
    if value is None:
        return "unknown_category"
    normalized = str(value).strip()
    return normalized or "unknown_category"


def _specialized_grouped_metric_statement(
    *,
    scope: RetrievalScope,
    date_from: date,
    date_to: date,
    metric_id: str,
    dimension: DimensionName,
):
    if dimension is DimensionName.PAYMENT_METHOD:
        return _payment_method_grouped_statement(
            scope=scope,
            date_from=date_from,
            date_to=date_to,
            metric_id=metric_id,
        )
    if dimension is DimensionName.CATEGORY:
        return _category_grouped_statement(
            scope=scope,
            date_from=date_from,
            date_to=date_to,
            metric_id=metric_id,
        )
    raise LiveAnalyticsUnsupportedError(
        f"Specialized grouped execution does not support dimension: {dimension.value}"
    )


def _payment_method_grouped_statement(
    *,
    scope: RetrievalScope,
    date_from: date,
    date_to: date,
    metric_id: str,
):
    _validate_specialized_metric_support(
        dimension=DimensionName.PAYMENT_METHOD,
        metric_ids=(metric_id,),
        supported_metric_ids=set(
            LIVE_SPECIALIZED_BREAKDOWN_METRIC_IDS[DimensionName.PAYMENT_METHOD.value]
        ),
    )
    bucket_expression = _payment_method_bucket_expression()
    metric_expression: Any
    if metric_id == "sales_total":
        metric_expression = func.coalesce(
            func.sum(func.coalesce(OrderPaymentHistory.payed, 0)),
            0,
        )
    else:
        metric_expression = func.count(func.distinct(OrderPaymentHistory.order_id))
    statement = (
        select(
            bucket_expression.label("bucket"),
            metric_expression.label("value"),
        )
        .select_from(Order)
        .join(OrderPaymentHistory, OrderPaymentHistory.order_id == Order.id)
        .outerjoin(Cashbox, Cashbox.id == OrderPaymentHistory.cashbox_id)
        .group_by(bucket_expression)
        .order_by(bucket_expression)
    )
    return apply_order_filters(
        statement,
        profile_id=scope.profile_id,
        date_from=date_from,
        date_to=date_to,
        branch_ids=scope.branch_ids,
        source=scope.source,
    )


def _category_grouped_statement(
    *,
    scope: RetrievalScope,
    date_from: date,
    date_to: date,
    metric_id: str,
):
    _validate_specialized_metric_support(
        dimension=DimensionName.CATEGORY,
        metric_ids=(metric_id,),
        supported_metric_ids=set(
            LIVE_SPECIALIZED_BREAKDOWN_METRIC_IDS[DimensionName.CATEGORY.value]
        ),
    )
    base_rows = _category_metric_rows_subquery(
        scope=scope,
        date_from=date_from,
        date_to=date_to,
    )
    metric_expression: Any
    if metric_id == "sales_total":
        metric_expression = func.coalesce(func.sum(base_rows.c.allocated_sales), 0)
    elif metric_id == "quantity_sold":
        metric_expression = func.coalesce(func.sum(base_rows.c.item_quantity), 0)
    else:
        metric_expression = func.count(func.distinct(base_rows.c.order_id))

    return (
        select(
            base_rows.c.bucket,
            metric_expression.label("value"),
        )
        .group_by(base_rows.c.bucket)
        .order_by(base_rows.c.bucket)
    )


def _category_metric_rows_subquery(
    *,
    scope: RetrievalScope,
    date_from: date,
    date_to: date,
):
    item_gross = (
        func.coalesce(OrderContent.item_price, 0)
        * func.coalesce(OrderContent.profile_menu_item_count, 0)
    )
    item_quantity = func.coalesce(OrderContent.profile_menu_item_count, 0)
    order_gross_total = func.sum(item_gross).over(partition_by=OrderContent.room_table_order_id)
    order_sales_total = func.coalesce(func.nullif(Order.final_total, 0), Order.total_price, 0)
    allocated_sales = case(
        (order_gross_total == 0, 0),
        else_=(order_sales_total * item_gross / order_gross_total),
    )
    bucket_expression = _category_bucket_expression()

    base_rows = (
        select(
            bucket_expression.label("bucket"),
            Order.id.label("order_id"),
            allocated_sales.label("allocated_sales"),
            item_quantity.label("item_quantity"),
        )
        .select_from(Order)
        .join(OrderContent, OrderContent.room_table_order_id == Order.id)
        .outerjoin(MenuItem, MenuItem.id == OrderContent.profile_menu_item_id)
        .outerjoin(MenuGroup, MenuGroup.id == MenuItem.group_id)
    )
    base_rows = apply_order_filters(
        base_rows,
        profile_id=scope.profile_id,
        date_from=date_from,
        date_to=date_to,
        branch_ids=scope.branch_ids,
        source=scope.source,
    ).subquery()


def _validate_specialized_metric_support(
    *,
    dimension: DimensionName,
    metric_ids: tuple[str, ...],
    supported_metric_ids: set[str],
) -> None:
    unsupported = sorted(
        metric_id for metric_id in metric_ids if metric_id not in supported_metric_ids
    )
    if unsupported:
        raise LiveAnalyticsUnsupportedError(
            "Live "
            f"{dimension.value} breakdown does not support metric dependencies yet: "
            f"{', '.join(unsupported)}"
        )


def _merge_grouped_metric_values(
    *,
    grouped_values_by_metric: dict[str, dict[Any, Decimal]],
    metric_ids: tuple[str, ...],
) -> list[Any]:
    buckets = {
        bucket
        for grouped_values in grouped_values_by_metric.values()
        for bucket in grouped_values
    }
    rows: list[Any] = []
    for bucket in sorted(buckets, key=_bucket_sort_key):
        payload: dict[str, Any] = {"bucket": bucket}
        for metric_id in metric_ids:
            payload[metric_id] = grouped_values_by_metric.get(metric_id, {}).get(
                bucket,
                Decimal("0"),
            )
        rows.append(SimpleNamespace(**payload))
    return rows


def _bucket_sort_key(value: Any) -> tuple[int, Any]:
    if value is None:
        return (4, "")
    if isinstance(value, date):
        return (0, value.isoformat())
    if isinstance(value, datetime):
        return (0, value.isoformat())
    if isinstance(value, Decimal):
        return (1, float(value))
    if isinstance(value, int | float):
        return (1, value)
    return (2, str(value))


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
