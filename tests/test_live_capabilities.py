from __future__ import annotations

from app.agent.live_capabilities import evaluate_live_retrieval_capability
from app.schemas.analysis import DimensionName, MetricName, RetrievalMode


def test_live_capabilities_allow_payment_method_average_check_breakdown() -> None:
    decision = evaluate_live_retrieval_capability(
        retrieval_mode=RetrievalMode.BREAKDOWN,
        retrieval_metric=MetricName.AVERAGE_CHECK,
        retrieval_dimension=DimensionName.PAYMENT_METHOD,
    )

    assert decision.allowed is True
    assert decision.reason_code == "ok"


def test_live_capabilities_allow_quantity_sold_total() -> None:
    decision = evaluate_live_retrieval_capability(
        retrieval_mode=RetrievalMode.TOTAL,
        retrieval_metric=MetricName.QUANTITY_SOLD,
        retrieval_dimension=None,
    )

    assert decision.allowed is True
    assert decision.reason_code == "ok"


def test_live_capabilities_allow_category_items_per_order_breakdown() -> None:
    decision = evaluate_live_retrieval_capability(
        retrieval_mode=RetrievalMode.BREAKDOWN,
        retrieval_metric=MetricName.ITEMS_PER_ORDER,
        retrieval_dimension=DimensionName.CATEGORY,
    )

    assert decision.allowed is True
    assert decision.reason_code == "ok"


def test_live_capabilities_reject_refund_rate_until_semantics_are_defined() -> None:
    decision = evaluate_live_retrieval_capability(
        retrieval_mode=RetrievalMode.TOTAL,
        retrieval_metric=MetricName.REFUND_RATE,
        retrieval_dimension=None,
    )

    assert decision.allowed is False
    assert decision.reason_code == "live_metric_semantics_unresolved"


def test_live_capabilities_reject_category_discount_share_breakdown() -> None:
    decision = evaluate_live_retrieval_capability(
        retrieval_mode=RetrievalMode.BREAKDOWN,
        retrieval_metric=MetricName.DISCOUNT_SHARE,
        retrieval_dimension=DimensionName.CATEGORY,
    )

    assert decision.allowed is False
    assert decision.reason_code == "live_breakdown_metric_not_supported"
