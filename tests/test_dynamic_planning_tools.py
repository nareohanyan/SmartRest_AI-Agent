from __future__ import annotations

from datetime import date

from app.agent.planning import plan_analysis
from app.agent.tools import compute_metrics_tool, fetch_total_metric_tool
from app.agent.tools.math_helpers import quantize_decimal
from app.schemas.analysis import AnalysisIntent, MetricName, RetrievalMode, TotalMetricRequest


def test_legacy_tool_import_surface_is_preserved() -> None:
    assert callable(compute_metrics_tool)
    assert callable(fetch_total_metric_tool)


def test_comparison_plan_includes_previous_period_retrieval() -> None:
    plan = plan_analysis("Compare sales 2026-03-10 to 2026-03-16 vs previous period")

    assert plan.intent is AnalysisIntent.COMPARISON
    assert plan.retrieval is not None
    assert plan.retrieval.mode is RetrievalMode.TOTAL
    assert plan.compare_to_previous_period is True
    assert plan.previous_period_retrieval is not None
    assert plan.previous_period_retrieval.mode is RetrievalMode.TOTAL
    assert plan.previous_period_retrieval.metric is MetricName.SALES_TOTAL
    assert plan.previous_period_retrieval.date_from == date(2026, 3, 3)
    assert plan.previous_period_retrieval.date_to == date(2026, 3, 9)


def test_average_check_total_uses_weighted_period_formula() -> None:
    date_from = date(2026, 3, 1)
    date_to = date(2026, 3, 7)

    average_check = fetch_total_metric_tool(
        TotalMetricRequest(
            metric=MetricName.AVERAGE_CHECK,
            date_from=date_from,
            date_to=date_to,
        )
    )
    sales_total = fetch_total_metric_tool(
        TotalMetricRequest(
            metric=MetricName.SALES_TOTAL,
            date_from=date_from,
            date_to=date_to,
        )
    )
    order_count = fetch_total_metric_tool(
        TotalMetricRequest(
            metric=MetricName.ORDER_COUNT,
            date_from=date_from,
            date_to=date_to,
        )
    )

    expected_average_check = quantize_decimal(sales_total.value / order_count.value)
    assert average_check.value == expected_average_check
