from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.agent.planning import _parse_question, _shift_months, _shift_years, plan_analysis
from app.agent.tools import compute_metrics_tool, fetch_total_metric_tool
from app.agent.tools import retrieval as retrieval_tools
from app.agent.tools.math_helpers import quantize_decimal
from app.schemas.analysis import (
    AnalysisIntent,
    BusinessQueryKind,
    DimensionName,
    ItemPerformanceMetric,
    MetricName,
    RankingMode,
    RetrievalMode,
    RetrievalScope,
    TotalMetricRequest,
)


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


def test_planner_resolves_registry_metric_alias_for_completed_orders() -> None:
    plan = plan_analysis("Show completed orders 2026-03-01 to 2026-03-07")

    assert plan.intent is AnalysisIntent.METRIC_TOTAL
    assert plan.retrieval is not None
    assert plan.retrieval.metric is MetricName.COMPLETED_ORDER_COUNT


def test_planner_resolves_registry_metric_alias_for_quantity_sold() -> None:
    plan = plan_analysis("Show quantity sold 2026-03-01 to 2026-03-07")

    assert plan.intent is AnalysisIntent.METRIC_TOTAL
    assert plan.retrieval is not None
    assert plan.retrieval.metric is MetricName.QUANTITY_SOLD


def test_planner_resolves_registry_metric_alias_for_gross_sales() -> None:
    plan = plan_analysis("Show gross sales 2026-03-01 to 2026-03-07")

    assert plan.intent is AnalysisIntent.METRIC_TOTAL
    assert plan.retrieval is not None
    assert plan.retrieval.metric is MetricName.GROSS_SALES_TOTAL


def test_planner_detects_breakdown_dimension_from_registry_aliases() -> None:
    plan = plan_analysis("Show sales by branch 2026-03-01 to 2026-03-07")

    assert plan.intent is AnalysisIntent.BREAKDOWN
    assert plan.retrieval is not None
    assert plan.retrieval.mode is RetrievalMode.BREAKDOWN
    assert plan.retrieval.dimension is DimensionName.BRANCH


def test_planner_detects_payment_method_dimension_from_payment_type_alias() -> None:
    plan = plan_analysis("Show sales by payment type 2026-03-01 to 2026-03-07")

    assert plan.intent is AnalysisIntent.BREAKDOWN
    assert plan.retrieval is not None
    assert plan.retrieval.mode is RetrievalMode.BREAKDOWN
    assert plan.retrieval.dimension is DimensionName.PAYMENT_METHOD


def test_planner_detects_payment_method_dimension_from_cash_vs_card_phrase() -> None:
    plan = plan_analysis("Show breakdown of sales by cash vs card 2026-03-01 to 2026-03-07")

    assert plan.intent is AnalysisIntent.BREAKDOWN
    assert plan.retrieval is not None
    assert plan.retrieval.mode is RetrievalMode.BREAKDOWN
    assert plan.retrieval.dimension is DimensionName.PAYMENT_METHOD


def test_planner_detects_category_dimension_from_menu_group_alias() -> None:
    plan = plan_analysis("Show sales by menu group 2026-03-01 to 2026-03-07")

    assert plan.intent is AnalysisIntent.BREAKDOWN
    assert plan.retrieval is not None
    assert plan.retrieval.mode is RetrievalMode.BREAKDOWN
    assert plan.retrieval.dimension is DimensionName.CATEGORY


def test_planner_routes_item_query_to_business_tool_plan() -> None:
    plan = plan_analysis("Show top 5 menu items 2026-03-01 to 2026-03-07")

    assert plan.business_query is not None
    assert plan.business_query.kind is BusinessQueryKind.ITEM_PERFORMANCE
    assert plan.business_query.item_metric is ItemPerformanceMetric.ITEM_REVENUE
    assert plan.business_query.limit == 5


def test_planner_routes_word_number_item_query_to_requested_k() -> None:
    plan = plan_analysis("Show top five menu items 2026-03-01 to 2026-03-07")

    assert plan.business_query is not None
    assert plan.business_query.kind is BusinessQueryKind.ITEM_PERFORMANCE
    assert plan.business_query.limit == 5


def test_parse_question_builds_structured_business_query_for_armenian_word_number_prompt() -> None:
    today = date.today()
    parsed = _parse_question("Նախորդ երկու ամսվա մեջ ամենաշատ վաճառված ապրանքը ո՞րն է եղել։")

    assert parsed.date_range is not None
    assert parsed.business_query is not None
    assert parsed.business_query.kind is BusinessQueryKind.ITEM_PERFORMANCE
    assert parsed.business_query.item_metric is ItemPerformanceMetric.QUANTITY_SOLD
    assert parsed.ranking_mode is RankingMode.TOP_K
    assert parsed.ranking_k == 1
    assert parsed.date_range.date_from == _shift_months(today, -2) + date.resolution
    assert parsed.date_range.date_to == today


def test_planner_routes_armenian_most_sold_items_to_quantity_metric() -> None:
    plan = plan_analysis("Որո՞նք են վերջին 3 ամսվա տոփ 5 ամենավաճառված ապրանքները։")

    assert plan.business_query is not None
    assert plan.business_query.kind is BusinessQueryKind.ITEM_PERFORMANCE
    assert plan.business_query.item_metric is ItemPerformanceMetric.QUANTITY_SOLD
    assert plan.business_query.limit == 5


def test_planner_routes_customer_query_to_business_tool_plan() -> None:
    plan = plan_analysis("Show customers 2026-03-01 to 2026-03-07")

    assert plan.business_query is not None
    assert plan.business_query.kind is BusinessQueryKind.CUSTOMER_SUMMARY


def test_planner_routes_receipt_query_to_business_tool_plan() -> None:
    plan = plan_analysis("Show receipt summary 2026-03-01 to 2026-03-07")

    assert plan.business_query is not None
    assert plan.business_query.kind is BusinessQueryKind.RECEIPT_SUMMARY


def test_relative_today_is_mapped_to_single_day_range() -> None:
    today = date.today()
    plan = plan_analysis("What are total sales today?")

    assert plan.intent is AnalysisIntent.METRIC_TOTAL
    assert plan.retrieval is not None
    assert plan.retrieval.date_from == today
    assert plan.retrieval.date_to == today


def test_relative_tomorrow_is_mapped_to_single_day_range() -> None:
    tomorrow = date.today() + date.resolution
    plan = plan_analysis("Какие продажи завтра?")

    assert plan.intent is AnalysisIntent.METRIC_TOTAL
    assert plan.retrieval is not None
    assert plan.retrieval.date_from == tomorrow
    assert plan.retrieval.date_to == tomorrow


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


def test_relative_past_month_is_mapped_to_rolling_thirty_days() -> None:
    today = date.today()
    plan = plan_analysis("Show sales for the past month")

    assert plan.intent is AnalysisIntent.METRIC_TOTAL
    assert plan.retrieval is not None
    assert plan.retrieval.date_from == today - date.resolution * 29
    assert plan.retrieval.date_to == today


def test_relative_armenian_three_month_item_query_is_supported() -> None:
    today = date.today()
    plan = plan_analysis("վերջին 3 ամսվա ամենաշատ վաճառված ապրանքը")

    assert plan.business_query is not None
    assert plan.business_query.kind is BusinessQueryKind.ITEM_PERFORMANCE
    assert plan.business_query.date_to == today
    assert plan.business_query.date_from == _shift_months(today, -3) + date.resolution
    assert plan.business_query.limit == 1


def test_relative_armenian_word_number_item_query_is_supported() -> None:
    today = date.today()
    plan = plan_analysis("Նախորդ երկու ամսվա մեջ ամենաշատ վաճառված ապրանքը ո՞րն է եղել։")

    assert plan.business_query is not None
    assert plan.business_query.kind is BusinessQueryKind.ITEM_PERFORMANCE
    assert plan.business_query.item_metric is ItemPerformanceMetric.QUANTITY_SOLD
    assert plan.business_query.date_to == today
    assert plan.business_query.date_from == _shift_months(today, -2) + date.resolution
    assert plan.business_query.limit == 1


def test_relative_armenian_word_number_item_query_with_typo_variant_is_supported() -> None:
    today = date.today()
    plan = plan_analysis("Նախորդ երկու ամսվա մեջ ամենաշատ վաճարված ապրանքը ո՞րն է եղել։")

    assert plan.business_query is not None
    assert plan.business_query.kind is BusinessQueryKind.ITEM_PERFORMANCE
    assert plan.business_query.item_metric is ItemPerformanceMetric.QUANTITY_SOLD
    assert plan.business_query.date_to == today
    assert plan.business_query.date_from == _shift_months(today, -2) + date.resolution
    assert plan.business_query.limit == 1


def test_relative_russian_two_weeks_is_mapped_to_fourteen_days() -> None:
    today = date.today()
    plan = plan_analysis("Покажи продажи за последние 2 недели")

    assert plan.intent is AnalysisIntent.METRIC_TOTAL
    assert plan.retrieval is not None
    assert plan.retrieval.date_from == today - date.resolution * 13
    assert plan.retrieval.date_to == today


def test_relative_previous_month_is_mapped_to_previous_calendar_month() -> None:
    today = date.today()
    current_month_start = today.replace(day=1)
    previous_month_end = current_month_start - date.resolution
    previous_month_start = previous_month_end.replace(day=1)
    plan = plan_analysis("Покажи продажи за прошлый месяц")

    assert plan.intent is AnalysisIntent.METRIC_TOTAL
    assert plan.retrieval is not None
    assert plan.retrieval.date_from == previous_month_start
    assert plan.retrieval.date_to == previous_month_end


def test_armenian_possessive_revenue_form_routes_to_sales_total() -> None:
    today = date.today()
    current_month_start = today.replace(day=1)
    previous_month_end = current_month_start - date.resolution
    previous_month_start = previous_month_end.replace(day=1)

    plan = plan_analysis("Նախորդ ամսվա եկամուտս ինչքա՞նա կազմել։")

    assert plan.intent is AnalysisIntent.METRIC_TOTAL
    assert plan.retrieval is not None
    assert plan.retrieval.metric is MetricName.SALES_TOTAL
    assert plan.retrieval.date_from == previous_month_start
    assert plan.retrieval.date_to == previous_month_end


def test_relative_past_30_days_is_mapped_to_bounded_range() -> None:
    today = date.today()
    plan = plan_analysis("Show sales for the past 30 days")

    assert plan.intent is AnalysisIntent.METRIC_TOTAL
    assert plan.retrieval is not None
    assert plan.retrieval.date_from == today - date.resolution * 29
    assert plan.retrieval.date_to == today


def test_relative_this_year_is_mapped_to_year_start_until_today() -> None:
    today = date.today()
    plan = plan_analysis("Ցույց տուր վաճառքը այս տարի")

    assert plan.intent is AnalysisIntent.METRIC_TOTAL
    assert plan.retrieval is not None
    assert plan.retrieval.date_from == today.replace(month=1, day=1)
    assert plan.retrieval.date_to == today


def test_relative_past_two_years_is_mapped_to_rolling_year_window() -> None:
    today = date.today()
    plan = plan_analysis("Show sales for the past 2 years")

    assert plan.intent is AnalysisIntent.METRIC_TOTAL
    assert plan.retrieval is not None
    assert plan.retrieval.date_from == _shift_years(today, -2) + date.resolution
    assert plan.retrieval.date_to == today


def test_relative_last_year_is_mapped_to_previous_calendar_year() -> None:
    today = date.today()
    plan = plan_analysis("Show sales last year")

    assert plan.intent is AnalysisIntent.METRIC_TOTAL
    assert plan.retrieval is not None
    assert plan.retrieval.date_from == today.replace(year=today.year - 1, month=1, day=1)
    assert plan.retrieval.date_to == today.replace(year=today.year - 1, month=12, day=31)


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
            scope=RetrievalScope(profile_id=98),
        )
    )
    sales_total = fetch_total_metric_tool(
        TotalMetricRequest(
            metric=MetricName.SALES_TOTAL,
            date_from=date_from,
            date_to=date_to,
            scope=RetrievalScope(profile_id=98),
        )
    )
    order_count = fetch_total_metric_tool(
        TotalMetricRequest(
            metric=MetricName.ORDER_COUNT,
            date_from=date_from,
            date_to=date_to,
            scope=RetrievalScope(profile_id=98),
        )
    )

    expected_average_check = quantize_decimal(sales_total.value / order_count.value)
    assert average_check.value == expected_average_check


@pytest.fixture(autouse=True)
def _fake_live_analytics(monkeypatch: pytest.MonkeyPatch) -> None:
    class _LiveService:
        def get_total_metric(self, request: TotalMetricRequest):
            values = {
                MetricName.SALES_TOTAL: Decimal("700"),
                MetricName.GROSS_SALES_TOTAL: Decimal("760"),
                MetricName.ORDER_COUNT: Decimal("14"),
                MetricName.AVERAGE_CHECK: Decimal("50"),
                MetricName.QUANTITY_SOLD: Decimal("42"),
                MetricName.DISCOUNTED_ORDER_COUNT: Decimal("5"),
                MetricName.DISCOUNTED_ORDER_SHARE: Decimal("0.3571"),
                MetricName.ITEMS_PER_ORDER: Decimal("3"),
            }
            return type(
                "_Response",
                (),
                {
                    "metric": request.metric,
                    "date_from": request.date_from,
                    "date_to": request.date_to,
                    "value": values[request.metric],
                    "base_metrics": {
                        "sales_total": Decimal("700"),
                        "order_count": Decimal("14"),
                        "day_count": Decimal("7"),
                    },
                    "warnings": [],
                },
            )()

    monkeypatch.setattr(retrieval_tools, "get_live_analytics_service", lambda: _LiveService())
