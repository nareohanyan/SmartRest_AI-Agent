from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

from app.agent.formula_ast import (
    FormulaAst,
    RatioFormulaAst,
    formula_metric_dependencies,
    validate_formula_ast,
)


class MetricType(str, Enum):
    BASE = "base"
    DERIVED = "derived"


@dataclass(frozen=True)
class DimensionDefinition:
    dimension_id: str
    label: str
    aliases: tuple[str, ...]
    permission_class: str


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    label: str
    metric_type: MetricType
    description: str
    unit: str
    allowed_dimension_ids: tuple[str, ...]
    aliases: tuple[str, ...]
    permission_class: str
    formula_ast: FormulaAst | None = None
    dependencies: tuple[str, ...] = ()
    definition_version: str | None = None


_DIMENSIONS: tuple[DimensionDefinition, ...] = (
    DimensionDefinition(
        dimension_id="branch",
        label="Branch",
        aliases=("branch", "location", "restaurant", "store", "filial"),
        permission_class="branch_scope",
    ),
    DimensionDefinition(
        dimension_id="source",
        label="Source",
        aliases=("source", "channel", "delivery source", "partner", "platform"),
        permission_class="standard_dimension",
    ),
    DimensionDefinition(
        dimension_id="day",
        label="Day",
        aliases=("day", "date", "daily"),
        permission_class="standard_dimension",
    ),
    DimensionDefinition(
        dimension_id="hour",
        label="Hour",
        aliases=("hour", "hourly", "time of day"),
        permission_class="standard_dimension",
    ),
    DimensionDefinition(
        dimension_id="weekday",
        label="Weekday",
        aliases=("weekday", "day of week"),
        permission_class="standard_dimension",
    ),
    DimensionDefinition(
        dimension_id="payment_method",
        label="Payment Method",
        aliases=("payment method", "payment type", "card or cash", "payment"),
        permission_class="sensitive_operational_dimension",
    ),
    DimensionDefinition(
        dimension_id="category",
        label="Category",
        aliases=("category", "product category", "menu category"),
        permission_class="standard_dimension",
    ),
    DimensionDefinition(
        dimension_id="cashier",
        label="Cashier",
        aliases=("cashier", "operator", "employee"),
        permission_class="sensitive_people_dimension",
    ),
)


_METRICS: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        metric_id="sales_total",
        label="Sales Total",
        metric_type=MetricType.BASE,
        description="Total realized sales amount in selected period.",
        unit="currency",
        allowed_dimension_ids=(
            "branch",
            "source",
            "day",
            "hour",
            "weekday",
            "category",
            "payment_method",
        ),
        aliases=("sales", "net sales", "revenue", "real sales"),
        permission_class="financial_core",
    ),
    MetricDefinition(
        metric_id="order_count",
        label="Order Count",
        metric_type=MetricType.BASE,
        description="Number of completed orders.",
        unit="count",
        allowed_dimension_ids=(
            "branch",
            "source",
            "day",
            "hour",
            "weekday",
            "category",
            "payment_method",
            "cashier",
        ),
        aliases=("orders", "completed orders", "transactions"),
        permission_class="operational_core",
    ),
    MetricDefinition(
        metric_id="completed_order_count",
        label="Completed Order Count",
        metric_type=MetricType.BASE,
        description="Number of orders successfully completed.",
        unit="count",
        allowed_dimension_ids=("branch", "source", "day", "hour", "weekday", "cashier"),
        aliases=("finished orders",),
        permission_class="operational_core",
    ),
    MetricDefinition(
        metric_id="canceled_order_count",
        label="Canceled Order Count",
        metric_type=MetricType.BASE,
        description="Number of orders canceled before completion.",
        unit="count",
        allowed_dimension_ids=("branch", "source", "day", "hour", "weekday", "cashier"),
        aliases=("canceled orders", "cancel count", "order cancellations"),
        permission_class="operational_sensitive",
    ),
    MetricDefinition(
        metric_id="refund_amount",
        label="Refund Amount",
        metric_type=MetricType.BASE,
        description="Total amount refunded to customers.",
        unit="currency",
        allowed_dimension_ids=("branch", "source", "day", "hour", "weekday", "payment_method"),
        aliases=("refunds", "returned money"),
        permission_class="financial_sensitive",
    ),
    MetricDefinition(
        metric_id="discount_amount",
        label="Discount Amount",
        metric_type=MetricType.BASE,
        description="Total amount discounted from sales.",
        unit="currency",
        allowed_dimension_ids=("branch", "source", "day", "hour", "weekday", "category"),
        aliases=("discounts", "promo discounts"),
        permission_class="financial_core",
    ),
    MetricDefinition(
        metric_id="average_check",
        label="Average Check",
        metric_type=MetricType.DERIVED,
        description="Average realized sales per completed order.",
        unit="currency",
        allowed_dimension_ids=(
            "branch",
            "source",
            "day",
            "hour",
            "weekday",
            "category",
            "payment_method",
        ),
        aliases=("avg check", "average order value", "aov"),
        permission_class="financial_core",
        formula_ast=RatioFormulaAst(
            numerator_metric_id="sales_total",
            denominator_metric_id="completed_order_count",
        ),
        dependencies=("sales_total", "completed_order_count"),
        definition_version="v2",
    ),
    MetricDefinition(
        metric_id="refund_rate",
        label="Refund Rate",
        metric_type=MetricType.DERIVED,
        description="Refund amount as a share of sales.",
        unit="ratio",
        allowed_dimension_ids=("branch", "source", "day", "weekday", "payment_method"),
        aliases=("refund share",),
        permission_class="financial_sensitive",
        formula_ast=RatioFormulaAst(
            numerator_metric_id="refund_amount",
            denominator_metric_id="sales_total",
        ),
        dependencies=("refund_amount", "sales_total"),
    ),
    MetricDefinition(
        metric_id="discount_share",
        label="Discount Share",
        metric_type=MetricType.DERIVED,
        description="Discount amount as a share of sales.",
        unit="ratio",
        allowed_dimension_ids=("branch", "source", "day", "weekday", "category"),
        aliases=("discount rate",),
        permission_class="financial_core",
        formula_ast=RatioFormulaAst(
            numerator_metric_id="discount_amount",
            denominator_metric_id="sales_total",
        ),
        dependencies=("discount_amount", "sales_total"),
    ),
)


def _normalize_token(token: str) -> str:
    return token.strip().lower()


@lru_cache(maxsize=1)
def get_dimension_registry() -> dict[str, DimensionDefinition]:
    registry = {dimension.dimension_id: dimension for dimension in _DIMENSIONS}
    if len(registry) != len(_DIMENSIONS):
        raise ValueError("Duplicate dimension_id found in canonical dimension registry.")
    return registry


@lru_cache(maxsize=1)
def get_metric_registry() -> dict[str, MetricDefinition]:
    registry = {metric.metric_id: metric for metric in _METRICS}
    if len(registry) != len(_METRICS):
        raise ValueError("Duplicate metric_id found in canonical metric registry.")

    known_metric_ids = set(registry)
    known_dimension_ids = set(get_dimension_registry())
    for metric in registry.values():
        missing_dimensions = set(metric.allowed_dimension_ids).difference(known_dimension_ids)
        if missing_dimensions:
            joined = ", ".join(sorted(missing_dimensions))
            raise ValueError(
                f"Metric `{metric.metric_id}` references unknown dimensions: {joined}"
            )

        if metric.metric_type is MetricType.DERIVED:
            if metric.formula_ast is None:
                raise ValueError(f"Derived metric `{metric.metric_id}` must define formula_ast")
            validate_formula_ast(ast=metric.formula_ast, known_metric_ids=known_metric_ids)
            formula_dependencies = formula_metric_dependencies(metric.formula_ast)
            dependency_set = set(metric.dependencies)
            if formula_dependencies != dependency_set:
                raise ValueError(
                    f"Derived metric `{metric.metric_id}` dependencies mismatch formula_ast refs."
                )
        elif metric.formula_ast is not None:
            raise ValueError(f"Base metric `{metric.metric_id}` must not define formula_ast")

    return registry


@lru_cache(maxsize=1)
def get_metric_alias_index() -> dict[str, str]:
    alias_index: dict[str, str] = {}
    for metric in get_metric_registry().values():
        for token in (metric.metric_id, *metric.aliases):
            normalized = _normalize_token(token)
            if normalized in alias_index and alias_index[normalized] != metric.metric_id:
                raise ValueError(f"Metric alias collision for token `{normalized}`")
            alias_index[normalized] = metric.metric_id
    return alias_index


@lru_cache(maxsize=1)
def get_dimension_alias_index() -> dict[str, str]:
    alias_index: dict[str, str] = {}
    for dimension in get_dimension_registry().values():
        for token in (dimension.dimension_id, *dimension.aliases):
            normalized = _normalize_token(token)
            if normalized in alias_index and alias_index[normalized] != dimension.dimension_id:
                raise ValueError(f"Dimension alias collision for token `{normalized}`")
            alias_index[normalized] = dimension.dimension_id
    return alias_index


def resolve_metric_id(token: str) -> str | None:
    return get_metric_alias_index().get(_normalize_token(token))


def resolve_dimension_id(token: str) -> str | None:
    return get_dimension_alias_index().get(_normalize_token(token))


def is_dimension_allowed_for_metric(*, metric_id: str, dimension_id: str) -> bool:
    metric = get_metric_registry().get(metric_id)
    if metric is None:
        return False
    return dimension_id in metric.allowed_dimension_ids


def all_metric_ids() -> tuple[str, ...]:
    return tuple(get_metric_registry().keys())


def all_dimension_ids() -> tuple[str, ...]:
    return tuple(get_dimension_registry().keys())
