from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import String, cast, desc, func, not_, or_, select
from sqlalchemy.orm import Session

from app.agent.services.smartrest_query_support import apply_order_filters, source_filter_clause
from app.agent.tools.math_helpers import quantize_decimal
from app.schemas.analysis import (
    CustomerSummaryRequest,
    CustomerSummaryResponse,
    ItemPerformanceItem,
    ItemPerformanceMetric,
    ItemPerformanceRequest,
    ItemPerformanceResponse,
    RankingMode,
    ReceiptSummaryRequest,
    ReceiptSummaryResponse,
    RetrievalScope,
)
from app.smartrest.models import (
    FiscalReceipt,
    MenuItem,
    Order,
    OrderContent,
    get_sync_session_factory,
)


class LiveBusinessToolsService:
    def __init__(self, session_factory: Callable[[], Session] | None = None) -> None:
        self._session_factory = session_factory or get_sync_session_factory()

    def get_item_performance(self, request: ItemPerformanceRequest) -> ItemPerformanceResponse:
        scope = _require_scope(request.scope)
        metric_expression = _item_metric_expression(request.metric)

        with self._session_factory() as session:
            statement = (
                select(
                    OrderContent.profile_menu_item_id.label("menu_item_id"),
                    MenuItem.name.label("name"),
                    MenuItem.name_ru.label("name_ru"),
                    MenuItem.name_en.label("name_en"),
                    metric_expression.label("metric_value"),
                )
                .join(Order, Order.id == OrderContent.room_table_order_id)
                .outerjoin(MenuItem, MenuItem.id == OrderContent.profile_menu_item_id)
            )
            statement = apply_order_filters(
                statement,
                profile_id=scope.profile_id,
                date_from=request.date_from,
                date_to=request.date_to,
                branch_ids=scope.branch_ids,
                source=scope.source,
            )
            if request.item_query is not None:
                pattern = f"%{request.item_query.strip()}%"
                statement = statement.where(
                    or_(
                        MenuItem.name.ilike(pattern),
                        MenuItem.name_ru.ilike(pattern),
                        MenuItem.name_en.ilike(pattern),
                    )
                )
            if request.exclude_item_query is not None:
                exclude_pattern = f"%{request.exclude_item_query.strip()}%"
                statement = statement.where(
                    not_(
                        or_(
                            MenuItem.name.ilike(exclude_pattern),
                            MenuItem.name_ru.ilike(exclude_pattern),
                            MenuItem.name_en.ilike(exclude_pattern),
                        )
                    )
                )

            order_expression = (
                desc(metric_expression)
                if request.ranking_mode is RankingMode.TOP_K
                else metric_expression.asc()
            )
            statement = (
                statement.group_by(
                    OrderContent.profile_menu_item_id,
                    MenuItem.name,
                    MenuItem.name_ru,
                    MenuItem.name_en,
                )
                .order_by(order_expression, OrderContent.profile_menu_item_id.asc())
                .limit(request.limit)
            )
            rows = session.execute(statement).all()

        items = [
            ItemPerformanceItem(
                menu_item_id=int(row.menu_item_id) if row.menu_item_id is not None else None,
                name=_coalesce_item_name(row),
                value=quantize_decimal(Decimal(str(row.metric_value or 0))),
            )
            for row in rows
        ]
        return ItemPerformanceResponse(
            metric=request.metric,
            date_from=request.date_from,
            date_to=request.date_to,
            ranking_mode=request.ranking_mode,
            items=items,
            warnings=[],
        )

    def get_customer_summary(self, request: CustomerSummaryRequest) -> CustomerSummaryResponse:
        scope = _require_scope(request.scope)
        with self._session_factory() as session:
            statement = select(
                func.count(func.distinct(Order.client_id)).label("unique_clients"),
                func.count(Order.id)
                .filter(Order.client_id.is_not(None))
                .label("identified_order_count"),
                func.count(Order.id).label("total_order_count"),
            )
            statement = apply_order_filters(
                statement,
                profile_id=scope.profile_id,
                date_from=request.date_from,
                date_to=request.date_to,
                branch_ids=scope.branch_ids,
                source=scope.source,
            )
            row = session.execute(statement).one()

        unique_clients = int(row.unique_clients or 0)
        identified_order_count = int(row.identified_order_count or 0)
        total_order_count = int(row.total_order_count or 0)
        average_orders = Decimal("0")
        if unique_clients > 0:
            average_orders = Decimal(str(identified_order_count)) / Decimal(str(unique_clients))

        return CustomerSummaryResponse(
            date_from=request.date_from,
            date_to=request.date_to,
            unique_clients=unique_clients,
            identified_order_count=identified_order_count,
            total_order_count=total_order_count,
            average_orders_per_identified_client=quantize_decimal(average_orders),
            warnings=[],
        )

    def get_receipt_summary(self, request: ReceiptSummaryRequest) -> ReceiptSummaryResponse:
        scope = _require_scope(request.scope)
        with self._session_factory() as session:
            summary_statement = (
                select(
                    func.count(FiscalReceipt.id).label("receipt_count"),
                    func.count(FiscalReceipt.order_id)
                    .filter(FiscalReceipt.order_id.is_not(None))
                    .label("linked_order_count"),
                )
                .outerjoin(Order, Order.id == FiscalReceipt.order_id)
                .where(FiscalReceipt.profile_id == scope.profile_id)
            )
            if request.date_from is not None:
                summary_statement = summary_statement.where(
                    func.date(FiscalReceipt.created_at) >= request.date_from
                )
            if request.date_to is not None:
                summary_statement = summary_statement.where(
                    func.date(FiscalReceipt.created_at) <= request.date_to
                )
            if scope.branch_ids:
                summary_statement = summary_statement.where(Order.branch_id.in_(scope.branch_ids))
            source_clause = source_filter_clause(scope.source)
            if source_clause is not None:
                summary_statement = summary_statement.where(source_clause)
            summary_row = session.execute(summary_statement).one()

            status_statement = (
                select(
                    cast(FiscalReceipt.status, String).label("status"),
                    func.count(FiscalReceipt.id).label("receipt_count"),
                )
                .outerjoin(Order, Order.id == FiscalReceipt.order_id)
                .where(FiscalReceipt.profile_id == scope.profile_id)
            )
            if request.date_from is not None:
                status_statement = status_statement.where(
                    func.date(FiscalReceipt.created_at) >= request.date_from
                )
            if request.date_to is not None:
                status_statement = status_statement.where(
                    func.date(FiscalReceipt.created_at) <= request.date_to
                )
            if scope.branch_ids:
                status_statement = status_statement.where(Order.branch_id.in_(scope.branch_ids))
            source_clause = source_filter_clause(scope.source)
            if source_clause is not None:
                status_statement = status_statement.where(source_clause)
            status_statement = status_statement.group_by(FiscalReceipt.status).order_by(
                FiscalReceipt.status
            )
            status_rows = session.execute(status_statement).all()

        status_counts = {
            (row.status if row.status is not None else "<null>"): int(row.receipt_count or 0)
            for row in status_rows
        }
        return ReceiptSummaryResponse(
            date_from=request.date_from,
            date_to=request.date_to,
            receipt_count=int(summary_row.receipt_count or 0),
            linked_order_count=int(summary_row.linked_order_count or 0),
            status_counts=status_counts,
            warnings=[],
        )


def _require_scope(scope: RetrievalScope | None) -> RetrievalScope:
    if scope is None:
        raise ValueError("Live SmartRest business tools require retrieval scope.")
    return scope


def _item_metric_expression(metric: ItemPerformanceMetric):
    if metric is ItemPerformanceMetric.ITEM_REVENUE:
        return func.coalesce(
            func.sum(
                func.coalesce(OrderContent.item_price, 0)
                * func.coalesce(OrderContent.profile_menu_item_count, 0)
            ),
            0,
        )
    if metric is ItemPerformanceMetric.QUANTITY_SOLD:
        return func.coalesce(func.sum(func.coalesce(OrderContent.profile_menu_item_count, 0)), 0)
    if metric is ItemPerformanceMetric.DISTINCT_ORDERS:
        return func.count(func.distinct(Order.id))
    raise ValueError(f"Unsupported item performance metric: {metric.value}")


def _coalesce_item_name(row: object) -> str:
    for field_name in ("name", "name_ru", "name_en"):
        value = getattr(row, field_name, None)
        if value is not None and str(value).strip():
            return str(value).strip()
    menu_item_id = getattr(row, "menu_item_id", None)
    if menu_item_id is None:
        return "unknown_item"
    return f"item_{menu_item_id}"
