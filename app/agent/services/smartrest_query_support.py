from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import case, func

from app.smartrest.models import Order

_SOURCE_ALIASES = {
    "delivery": "takeaway",
    "takeaway": "takeaway",
    "pickup": "takeaway",
    "in_store": "in_store",
    "in-store": "in_store",
    "instore": "in_store",
    "dine_in": "in_store",
    "dine-in": "in_store",
    "restaurant": "in_store",
}


def normalize_source_filter(source: str | None) -> str | None:
    if source is None:
        return None

    normalized = _SOURCE_ALIASES.get(source.strip().lower())
    if normalized is None:
        raise ValueError(f"Unsupported source: {source}")
    return normalized


def sales_total_expression() -> Any:
    # In the synced SmartRest dataset final_total is often zero.
    # total_price carries the real sales amount for those rows.
    return func.coalesce(
        func.sum(func.coalesce(func.nullif(Order.final_total, 0), Order.total_price, 0)),
        0,
    )


def source_bucket_expression() -> Any:
    return case((Order.is_delivery.is_(True), "takeaway"), else_="in_store")


def source_filter_clause(source: str | None) -> Any | None:
    normalized = normalize_source_filter(source)
    if normalized is None:
        return None
    if normalized == "takeaway":
        return Order.is_delivery.is_(True)
    return Order.is_delivery.is_(False)


def apply_order_filters(
    statement: Any,
    *,
    profile_id: int,
    date_from: date | None,
    date_to: date | None,
    branch_ids: list[int] | None = None,
    source: str | None = None,
) -> Any:
    statement = statement.where(Order.profile_id == profile_id)
    if date_from is not None:
        statement = statement.where(func.date(Order.order_create_date) >= date_from)
    if date_to is not None:
        statement = statement.where(func.date(Order.order_create_date) <= date_to)
    if branch_ids:
        statement = statement.where(Order.branch_id.in_(branch_ids))

    source_clause = source_filter_clause(source)
    if source_clause is not None:
        statement = statement.where(source_clause)
    return statement
