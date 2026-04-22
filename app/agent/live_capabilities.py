from __future__ import annotations

from dataclasses import dataclass

from app.agent.metric_registry import MetricType, get_metric_registry
from app.schemas.analysis import DimensionName, MetricName, RetrievalMode

LIVE_BASE_METRIC_IDS = frozenset(
    {
        "sales_total",
        "order_count",
        "completed_order_count",
        "discounted_order_count",
        "discount_amount",
        "delivery_order_count",
        "dine_in_order_count",
        "quantity_sold",
    }
)

LIVE_SPECIALIZED_BREAKDOWN_METRIC_IDS: dict[str, frozenset[str]] = {
    DimensionName.PAYMENT_METHOD.value: frozenset(
        {"sales_total", "order_count", "completed_order_count"}
    ),
    DimensionName.CATEGORY.value: frozenset(
        {"sales_total", "order_count", "completed_order_count", "quantity_sold"}
    ),
}

LIVE_SEMANTICS_UNRESOLVED_METRIC_IDS = frozenset(
    {
        MetricName.CANCELED_ORDER_COUNT.value,
        MetricName.REFUND_AMOUNT.value,
        MetricName.REFUND_RATE.value,
    }
)


@dataclass(frozen=True)
class LiveCapabilityDecision:
    allowed: bool
    reason_code: str
    reason_message: str


def evaluate_live_retrieval_capability(
    *,
    retrieval_mode: RetrievalMode | None,
    retrieval_metric: MetricName | None,
    retrieval_dimension: DimensionName | None,
) -> LiveCapabilityDecision:
    if retrieval_mode is None or retrieval_metric is None:
        return LiveCapabilityDecision(
            allowed=True,
            reason_code="ok",
            reason_message="No live retrieval capability check required.",
        )

    required_metric_ids = _required_live_metric_ids(retrieval_metric)
    unresolved_metric_ids = sorted(
        metric_id
        for metric_id in required_metric_ids
        if metric_id in LIVE_SEMANTICS_UNRESOLVED_METRIC_IDS
    )
    if unresolved_metric_ids:
        joined = ", ".join(unresolved_metric_ids)
        return LiveCapabilityDecision(
            allowed=False,
            reason_code="live_metric_semantics_unresolved",
            reason_message=(
                "Live SmartRest semantics are not validated yet for metric dependencies: "
                f"{joined}."
            ),
        )

    if retrieval_mode is RetrievalMode.TIMESERIES:
        if retrieval_dimension is not DimensionName.DAY:
            return LiveCapabilityDecision(
                allowed=False,
                reason_code="live_timeseries_dimension_not_supported",
                reason_message="Live timeseries currently supports day dimension only.",
            )
        return _allow_live_capability()

    if retrieval_mode is RetrievalMode.BREAKDOWN:
        supported_metric_ids = LIVE_BASE_METRIC_IDS
        if retrieval_dimension is not None:
            supported_metric_ids = LIVE_SPECIALIZED_BREAKDOWN_METRIC_IDS.get(
                retrieval_dimension.value,
                LIVE_BASE_METRIC_IDS,
            )

        unsupported_metric_ids = sorted(
            metric_id for metric_id in required_metric_ids if metric_id not in supported_metric_ids
        )
        if unsupported_metric_ids:
            joined = ", ".join(unsupported_metric_ids)
            return LiveCapabilityDecision(
                allowed=False,
                reason_code="live_breakdown_metric_not_supported",
                reason_message=(
                    "Live breakdown does not support metric dependencies for this "
                    f"dimension yet: {joined}."
                ),
            )
        return _allow_live_capability()

    unsupported_metric_ids = sorted(
        metric_id for metric_id in required_metric_ids if metric_id not in LIVE_BASE_METRIC_IDS
    )
    if unsupported_metric_ids:
        joined = ", ".join(unsupported_metric_ids)
        return LiveCapabilityDecision(
            allowed=False,
            reason_code="live_metric_not_supported",
            reason_message=(
                "Live analytics do not support metric dependencies yet: "
                f"{joined}."
            ),
        )

    return _allow_live_capability()


def _allow_live_capability() -> LiveCapabilityDecision:
    return LiveCapabilityDecision(
        allowed=True,
        reason_code="ok",
        reason_message="Live retrieval capability is supported.",
    )


def _required_live_metric_ids(metric: MetricName) -> tuple[str, ...]:
    metric_definition = get_metric_registry().get(metric.value)
    if metric_definition is None:
        return (metric.value,)
    if metric_definition.metric_type is MetricType.BASE:
        return (metric.value,)
    return tuple(metric_definition.dependencies)
