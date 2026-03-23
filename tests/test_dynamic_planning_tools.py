from __future__ import annotations

from datetime import date

from app.agent.planning import plan_analysis
from app.agent.tools import compute_metrics_tool, fetch_total_metric_tool
from app.agent.tools.math_helpers import quantize_decimal
from app.schemas.analysis import AnalysisIntent, MetricName, RetrievalMode, TotalMetricRequest


def test_legacy_tool_import_surface_is_preserved() -> None:
    assert callable(compute_metrics_tool)
    assert callable(fetch_total_metric_tool)


def test_hy_metric_total_routes_to_supported_intent() -> None:
    plan = plan_analysis("Ի՞նչ էր ընդհանուր վաճառքը 2026-03-01 to 2026-03-07 ժամանակահատվածում։")

    assert plan.intent is AnalysisIntent.METRIC_TOTAL
    assert plan.retrieval is not None
    assert plan.retrieval.mode is RetrievalMode.TOTAL
    assert plan.retrieval.metric is MetricName.SALES_TOTAL
    assert plan.retrieval.date_from == date(2026, 3, 1)
    assert plan.retrieval.date_to == date(2026, 3, 7)


def test_ru_comparison_routes_to_supported_intent() -> None:
    plan = plan_analysis("Сравни продажи 2026-03-10 to 2026-03-16 с предыдущим периодом.")

    assert plan.intent is AnalysisIntent.COMPARISON
    assert plan.retrieval is not None
    assert plan.previous_period_retrieval is not None
    assert plan.retrieval.mode is RetrievalMode.TOTAL
    assert plan.previous_period_retrieval.mode is RetrievalMode.TOTAL


def test_hy_ranking_detects_requested_k_value() -> None:
    plan = plan_analysis("Ցույց տուր ըստ աղբյուրի լավագույն 5 վաճառքները 2026-03-01 to 2026-03-07։")

    assert plan.intent is AnalysisIntent.RANKING
    assert plan.ranking is not None
    assert plan.ranking.k == 5


def test_relative_today_is_mapped_to_single_day_range() -> None:
    today = date.today()
    plan = plan_analysis("What are total sales today?")

    assert plan.intent is AnalysisIntent.METRIC_TOTAL
    assert plan.retrieval is not None
    assert plan.retrieval.date_from == today
    assert plan.retrieval.date_to == today


def test_relative_yesterday_is_mapped_to_single_day_range() -> None:
    yesterday = date.today() - date.resolution
    plan = plan_analysis("Какие продажи вчера?")

    assert plan.intent is AnalysisIntent.METRIC_TOTAL
    assert plan.retrieval is not None
    assert plan.retrieval.date_from == yesterday
    assert plan.retrieval.date_to == yesterday


def test_relative_last_week_is_mapped_to_previous_seven_days() -> None:
    today = date.today()
    plan = plan_analysis("Compare sales last week vs previous period")

    assert plan.intent is AnalysisIntent.COMPARISON
    assert plan.retrieval is not None
    assert plan.retrieval.date_from == today - date.resolution * 7
    assert plan.retrieval.date_to == today - date.resolution


def test_relative_this_month_is_mapped_to_month_start_until_today() -> None:
    today = date.today()
    plan = plan_analysis("Այս ամիս ընդհանուր վաճառքը ցույց տուր")

    assert plan.intent is AnalysisIntent.METRIC_TOTAL
    assert plan.retrieval is not None
    assert plan.retrieval.date_from == today.replace(day=1)
    assert plan.retrieval.date_to == today


def test_relative_past_30_days_is_mapped_to_bounded_range() -> None:
    today = date.today()
    plan = plan_analysis("Show sales for the past 30 days")

    assert plan.intent is AnalysisIntent.METRIC_TOTAL
    assert plan.retrieval is not None
    assert plan.retrieval.date_from == today - date.resolution * 29
    assert plan.retrieval.date_to == today


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
