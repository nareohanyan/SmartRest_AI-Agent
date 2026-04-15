from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from functools import lru_cache

from app.agent.metric_registry import get_dimension_alias_index, get_metric_alias_index
from app.agent.parser_concepts import (
    ITEM_DISTINCT_ORDER_TERMS,
    ITEM_ENTITY_TERMS,
    ITEM_QUANTITY_TERMS,
    ITEM_REVENUE_TERMS,
    contains_business_signal,
    detect_dimension,
    detect_item_metric,
    detect_metric,
    extract_ranking_k,
    is_customer_business_query,
    is_item_business_query,
    is_receipt_business_query,
    needs_breakdown,
    needs_comparison,
    needs_ranking,
    needs_trend,
    sales_concept_terms,
)
from app.agent.parser_normalization import (
    build_semantic_base_tokens,
    semantic_tokens,
)
from app.agent.parser_normalization import (
    normalize_smalltalk_text as _normalize_smalltalk_text,
)
from app.agent.parser_normalization import (
    normalize_text as _normalize_text,
)
from app.agent.parser_numbers import normalize_number_words
from app.agent.parser_policy import decide_policy
from app.agent.parser_structures import (
    ParsedBusinessQuery,
    ParsedDateRange,
    ParsedQuestion,
    ParserPolicyAction,
)
from app.agent.planner_lexicon import get_planner_lexicon
from app.schemas.analysis import (
    AnalysisIntent,
    AnalysisPlan,
    BusinessQueryKind,
    BusinessQuerySpec,
    DimensionName,
    ItemPerformanceMetric,
    LegacyReportTask,
    MetricName,
    RankingMode,
    RankingSpec,
    RetrievalMode,
    RetrievalSpec,
)
from app.schemas.calculations import (
    CalculationSpec,
    DeltaCalculationSpec,
    PercentChangeCalculationSpec,
    PerDayRateCalculationSpec,
)
from app.schemas.reports import ReportType

_DATE_RANGE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:to|-)\s*(\d{4}-\d{2}-\d{2})")
_ARMENIAN_CHAR_RE = re.compile(r"[\u0531-\u058F]")
_CYRILLIC_CHAR_RE = re.compile(r"[\u0400-\u04FF]")
_MULTI_TASK_SPLIT_RE = re.compile(r"\s+(?:and|և|и)\s+", re.IGNORECASE)
_PLANNER_LEXICON = get_planner_lexicon()
_ITEM_QUERY_RE = re.compile(
    r"(?:item|dish|menu item|product|ապրանք|ուտեստ|блюдо|товар)\s+"
    r"([a-zA-Z0-9\u0400-\u04FF\u0531-\u058F'’ -]{2,})"
)
_EN_NUMERIC_RELATIVE_RE = re.compile(
    r"\b(?:last|past|previous)\s+(\d{1,3})\s+"
    r"(day|days|week|weeks|month|months|year|years)\b"
)
_HY_NUMERIC_RELATIVE_RE = re.compile(
    r"\b(?:վերջին|նախորդ|անցած)\s+(\d{1,3})\s+"
    r"(օր|օրվա|օրերի|շաբաթ|շաբաթվա|շաբաթների|ամիս|ամսվա|ամիսների|տարի|տարվա|տարիների)\b"
)
_RU_NUMERIC_RELATIVE_RE = re.compile(
    r"\b(?:последн\w*|предыдущ\w*|прошл\w*)\s+(\d{1,3})\s+"
    r"(день|дня|дней|неделя|недели|недель|месяц|месяца|месяцев|год|года|лет)\b"
)
_NUMERIC_RELATIVE_MAX_VALUE = 120


class PlanningError(ValueError):
    """Raised when a request cannot be planned safely."""


def _is_armenian_text(text: str) -> bool:
    return _ARMENIAN_CHAR_RE.search(text) is not None


def _is_cyrillic_text(text: str) -> bool:
    return _CYRILLIC_CHAR_RE.search(text) is not None


def _question_language(text: str) -> str:
    if _is_armenian_text(text):
        return "hy"
    if _is_cyrillic_text(text):
        return "ru"
    return "en"


def _normalize_question_text(question: str) -> str:
    return _normalize_text(normalize_number_words(_normalize_text(question)))


@lru_cache(maxsize=1)
def _semantic_base_tokens() -> frozenset[str]:
    lexicon_fields = (
        _PLANNER_LEXICON.metric_terms,
        _PLANNER_LEXICON.high_priority_business_terms,
        _PLANNER_LEXICON.operation_terms,
        _PLANNER_LEXICON.dimension_terms,
        _PLANNER_LEXICON.average_metric_terms,
        _PLANNER_LEXICON.order_metric_terms,
        _PLANNER_LEXICON.sales_metric_terms,
        _PLANNER_LEXICON.breakdown_terms,
        _PLANNER_LEXICON.ranking_top_terms,
        _PLANNER_LEXICON.ranking_bottom_terms,
        _PLANNER_LEXICON.trend_terms,
        _PLANNER_LEXICON.comparison_terms,
        ITEM_ENTITY_TERMS,
        ITEM_QUANTITY_TERMS,
        ITEM_REVENUE_TERMS,
        ITEM_DISTINCT_ORDER_TERMS,
        sales_concept_terms(_PLANNER_LEXICON),
        {alias for alias in get_metric_alias_index() if " " not in alias},
        {alias for alias in get_dimension_alias_index() if " " not in alias},
    )
    return build_semantic_base_tokens(*lexicon_fields)


def _semantic_tokens(normalized_question: str) -> set[str]:
    return semantic_tokens(normalized_question, base_tokens=_semantic_base_tokens())


def _contains_business_signal(normalized_question: str) -> bool:
    return contains_business_signal(
        normalized_question,
        _semantic_tokens(normalized_question),
        lexicon=_PLANNER_LEXICON,
    )


def _is_smalltalk(question: str) -> bool:
    normalized = _normalize_smalltalk_text(question)
    if not normalized:
        return False

    if _contains_business_signal(normalized):
        return False

    if normalized in _PLANNER_LEXICON.pure_smalltalk_phrases:
        return True

    tokens = normalized.split()
    if not tokens or len(tokens) > 7:
        return False

    if not any(token in _PLANNER_LEXICON.greeting_tokens for token in tokens):
        return False

    allowed_tokens = (
        _PLANNER_LEXICON.greeting_tokens
        | _PLANNER_LEXICON.smalltalk_support_tokens
    )
    return all(token in allowed_tokens for token in tokens)


def _parse_date_range(question: str) -> tuple[date, date] | None:
    match = _DATE_RANGE_RE.search(question)
    if match:
        return (date.fromisoformat(match.group(1)), date.fromisoformat(match.group(2)))
    return _parse_relative_date_range(question)


def _has_any_phrase(text: str, phrases: set[str]) -> bool:
    return any(phrase in text for phrase in phrases)


def _parse_relative_date_range(
    question: str,
    *,
    reference_date: date | None = None,
) -> tuple[date, date] | None:
    normalized = _normalize_question_text(question)
    if not normalized:
        return None

    today = reference_date or date.today()
    numeric_relative_range = _parse_numeric_relative_date_range(
        normalized=normalized,
        reference_date=today,
    )
    if numeric_relative_range is not None:
        return numeric_relative_range

    tomorrow = today + timedelta(days=1)
    yesterday = today - timedelta(days=1)
    last_week_start = today - timedelta(days=7)
    last_week_end = today - timedelta(days=1)
    month_start = today.replace(day=1)
    previous_month_end = month_start - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)
    past_30_days_start = today - timedelta(days=29)
    past_month_start = today - timedelta(days=29)
    year_start = today.replace(month=1, day=1)
    last_year_start = today.replace(year=today.year - 1, month=1, day=1)
    last_year_end = today.replace(year=today.year - 1, month=12, day=31)

    matches: list[tuple[date, date]] = []
    if _has_any_phrase(normalized, _PLANNER_LEXICON.relative_today_terms):
        matches.append((today, today))
    if _has_any_phrase(normalized, _PLANNER_LEXICON.relative_tomorrow_terms):
        matches.append((tomorrow, tomorrow))
    if _has_any_phrase(normalized, _PLANNER_LEXICON.relative_yesterday_terms):
        matches.append((yesterday, yesterday))
    if _has_any_phrase(normalized, _PLANNER_LEXICON.relative_last_week_terms):
        matches.append((last_week_start, last_week_end))
    if _has_any_phrase(normalized, _PLANNER_LEXICON.relative_this_month_terms):
        matches.append((month_start, today))
    if _has_any_phrase(normalized, _PLANNER_LEXICON.relative_past_month_terms):
        matches.append((past_month_start, today))
    if _has_any_phrase(normalized, _PLANNER_LEXICON.relative_previous_month_terms):
        matches.append((previous_month_start, previous_month_end))
    if _has_any_phrase(normalized, _PLANNER_LEXICON.relative_past_30_days_terms):
        matches.append((past_30_days_start, today))
    if _has_any_phrase(normalized, _PLANNER_LEXICON.relative_this_year_terms):
        matches.append((year_start, today))
    if _has_any_phrase(normalized, _PLANNER_LEXICON.relative_last_year_terms):
        matches.append((last_year_start, last_year_end))

    if len(matches) == 1:
        return matches[0]
    return None


def _parse_numeric_relative_date_range(
    *,
    normalized: str,
    reference_date: date,
) -> tuple[date, date] | None:
    for pattern, unit_resolver in (
        (_EN_NUMERIC_RELATIVE_RE, _resolve_en_relative_unit),
        (_HY_NUMERIC_RELATIVE_RE, _resolve_hy_relative_unit),
        (_RU_NUMERIC_RELATIVE_RE, _resolve_ru_relative_unit),
    ):
        match = pattern.search(normalized)
        if not match:
            continue

        value = int(match.group(1))
        if value < 1 or value > _NUMERIC_RELATIVE_MAX_VALUE:
            return None

        unit = unit_resolver(match.group(2))
        if unit is None:
            return None

        return _materialize_numeric_relative_range(
            reference_date=reference_date,
            value=value,
            unit=unit,
        )
    return None


def _resolve_en_relative_unit(raw_unit: str) -> str | None:
    if raw_unit.startswith("day"):
        return "day"
    if raw_unit.startswith("week"):
        return "week"
    if raw_unit.startswith("month"):
        return "month"
    if raw_unit.startswith("year"):
        return "year"
    return None


def _resolve_hy_relative_unit(raw_unit: str) -> str | None:
    if raw_unit.startswith("օր"):
        return "day"
    if raw_unit.startswith("շաբաթ"):
        return "week"
    if raw_unit.startswith("ամիս") or raw_unit.startswith("ամս"):
        return "month"
    if raw_unit.startswith("տարի") or raw_unit.startswith("տար"):
        return "year"
    return None


def _resolve_ru_relative_unit(raw_unit: str) -> str | None:
    if raw_unit.startswith("д"):
        return "day"
    if raw_unit.startswith("недел") or raw_unit.startswith("неделя"):
        return "week"
    if raw_unit.startswith("меся"):
        return "month"
    if raw_unit.startswith("год") or raw_unit == "лет":
        return "year"
    return None


def _materialize_numeric_relative_range(
    *,
    reference_date: date,
    value: int,
    unit: str,
) -> tuple[date, date]:
    if unit == "day":
        return (reference_date - timedelta(days=value - 1), reference_date)
    if unit == "week":
        return (reference_date - timedelta(days=(value * 7) - 1), reference_date)
    if unit == "month":
        start = _shift_months(reference_date, -value) + timedelta(days=1)
        return (start, reference_date)
    if unit == "year":
        start = _shift_years(reference_date, -value) + timedelta(days=1)
        return (start, reference_date)
    raise PlanningError(f"Unsupported numeric relative unit: {unit}")


def _shift_months(base_date: date, months_delta: int) -> date:
    total_month_index = (base_date.year * 12) + (base_date.month - 1) + months_delta
    target_year, target_month_index = divmod(total_month_index, 12)
    target_month = target_month_index + 1
    target_day = min(
        base_date.day,
        calendar.monthrange(target_year, target_month)[1],
    )
    return date(target_year, target_month, target_day)


def _shift_years(base_date: date, years_delta: int) -> date:
    target_year = base_date.year + years_delta
    target_day = min(
        base_date.day,
        calendar.monthrange(target_year, base_date.month)[1],
    )
    return date(target_year, base_date.month, target_day)


def _detect_metric(question: str) -> MetricName | None:
    normalized = _normalize_question_text(question)
    return detect_metric(
        normalized,
        _semantic_tokens(normalized),
        metric_alias_index=get_metric_alias_index(),
        lexicon=_PLANNER_LEXICON,
    )


def _detect_dimension(question: str) -> DimensionName | None:
    normalized = _normalize_question_text(question)
    return detect_dimension(
        normalized,
        _semantic_tokens(normalized),
        dimension_alias_index=get_dimension_alias_index(),
    )


def _map_metric_to_legacy_report(metric: MetricName) -> ReportType | None:
    if metric is MetricName.SALES_TOTAL:
        return ReportType.SALES_TOTAL
    if metric is MetricName.ORDER_COUNT:
        return ReportType.ORDER_COUNT
    if metric is MetricName.AVERAGE_CHECK:
        return ReportType.AVERAGE_CHECK
    return None


def plan_legacy_tasks(question: str) -> list[LegacyReportTask] | None:
    normalized = _normalize_question_text(question)
    if not normalized or _is_smalltalk(question):
        return None

    if _needs_ranking(question) is not None or _needs_breakdown(question):
        return None

    if _has_any_phrase(normalized, _PLANNER_LEXICON.comparison_terms):
        return None

    if _has_any_phrase(normalized, _PLANNER_LEXICON.trend_terms):
        return None

    if _MULTI_TASK_SPLIT_RE.search(question) is None:
        return None

    date_range = _parse_date_range(question)
    if date_range is None:
        return None

    raw_parts = [
        part.strip(" ,.?")
        for part in _MULTI_TASK_SPLIT_RE.split(question)
        if part.strip()
    ]
    if len(raw_parts) < 2:
        return None

    tasks: list[LegacyReportTask] = []
    for index, part in enumerate(raw_parts, start=1):
        metric = _detect_metric(part)
        if metric is None:
            tasks.append(
                LegacyReportTask(
                    task_id=f"task_{index}",
                    user_subquery=part,
                    supported=False,
                    reason="unsupported_metric",
                )
            )
            continue

        report_id = _map_metric_to_legacy_report(metric)
        if report_id is None:
            tasks.append(
                LegacyReportTask(
                    task_id=f"task_{index}",
                    user_subquery=part,
                    metric=metric,
                    supported=False,
                    reason="unsupported_metric",
                )
            )
            continue

        tasks.append(
            LegacyReportTask(
                task_id=f"task_{index}",
                user_subquery=part,
                metric=metric,
                date_from=date_range[0],
                date_to=date_range[1],
                report_id=report_id,
            )
        )

    supported_count = sum(1 for task in tasks if task.supported)
    if supported_count == 0 or len(tasks) < 2:
        return None
    return tasks


def _needs_breakdown(question: str) -> bool:
    normalized = _normalize_question_text(question)
    return needs_breakdown(
        normalized,
        _semantic_tokens(normalized),
        has_dimension=_detect_dimension(question) is not None,
        lexicon=_PLANNER_LEXICON,
    )


def _extract_ranking_k(question: str) -> int:
    return extract_ranking_k(_normalize_question_text(question))


def _needs_ranking(question: str) -> RankingMode | None:
    return needs_ranking(_normalize_question_text(question), lexicon=_PLANNER_LEXICON)


def _needs_trend(question: str) -> bool:
    return needs_trend(_normalize_question_text(question), lexicon=_PLANNER_LEXICON)


def _needs_comparison(question: str) -> bool:
    normalized = _normalize_question_text(question)
    return needs_comparison(
        normalized,
        _semantic_tokens(normalized),
        lexicon=_PLANNER_LEXICON,
    )


def _is_item_business_query(question: str) -> bool:
    return is_item_business_query(_normalize_question_text(question))


def _is_customer_business_query(question: str) -> bool:
    return is_customer_business_query(_normalize_question_text(question))


def _is_receipt_business_query(question: str) -> bool:
    return is_receipt_business_query(_normalize_question_text(question))


def _detect_item_metric(question: str) -> ItemPerformanceMetric:
    normalized = _normalize_question_text(question)
    return detect_item_metric(normalized, _semantic_tokens(normalized))


def _extract_item_query(question: str) -> str | None:
    quote_match = re.search(r"[\"“](.+?)[\"”]", question)
    if quote_match:
        extracted = quote_match.group(1).strip()
        return extracted or None

    match = _ITEM_QUERY_RE.search(question)
    if not match:
        return None
    extracted = match.group(1).strip(" .,!?:;")
    if len(extracted) < 2:
        return None
    return extracted


def _parse_question(question: str) -> ParsedQuestion:
    normalized = _normalize_question_text(question)
    date_range = _parse_date_range(question)
    ranking_mode = _needs_ranking(question)
    ranking_k = _extract_ranking_k(question)
    inferred_ranking_mode = ranking_mode
    parsed_date_range = (
        ParsedDateRange(
            date_from=date_range[0],
            date_to=date_range[1],
        )
        if date_range is not None
        else None
    )
    dimension = _detect_dimension(question)
    business_query: ParsedBusinessQuery | None = None
    if parsed_date_range is not None:
        if _is_item_business_query(question):
            inferred_ranking_mode = ranking_mode or RankingMode.TOP_K
            business_query = ParsedBusinessQuery(
                kind=BusinessQueryKind.ITEM_PERFORMANCE,
                item_metric=_detect_item_metric(question),
                item_query=_extract_item_query(question),
            )
        elif _is_customer_business_query(question):
            business_query = ParsedBusinessQuery(kind=BusinessQueryKind.CUSTOMER_SUMMARY)
        elif _is_receipt_business_query(question):
            business_query = ParsedBusinessQuery(kind=BusinessQueryKind.RECEIPT_SUMMARY)

    return ParsedQuestion(
        normalized_question=normalized,
        language=_question_language(question),
        date_range=parsed_date_range,
        has_business_signal=_contains_business_signal(normalized),
        metric=_detect_metric(question),
        dimension=dimension,
        ranking_mode=(
            inferred_ranking_mode
            if (
                business_query is not None
                and business_query.kind is BusinessQueryKind.ITEM_PERFORMANCE
            )
            else ranking_mode
        ),
        ranking_k=ranking_k,
        wants_breakdown=needs_breakdown(
            normalized,
            _semantic_tokens(normalized),
            has_dimension=dimension is not None,
            lexicon=_PLANNER_LEXICON,
        ),
        wants_trend=_needs_trend(question),
        wants_comparison=_needs_comparison(question),
        business_query=business_query,
    )


def _build_business_plan(parsed: ParsedQuestion) -> AnalysisPlan | None:
    if parsed.date_range is None or parsed.business_query is None:
        return None

    date_from = parsed.date_range.date_from
    date_to = parsed.date_range.date_to

    if parsed.business_query.kind is BusinessQueryKind.ITEM_PERFORMANCE:
        item_metric = parsed.business_query.item_metric
        if item_metric is None:
            raise PlanningError("Item performance parse requires item_metric.")
        return AnalysisPlan(
            intent=AnalysisIntent.RANKING,
            business_query=BusinessQuerySpec(
                kind=BusinessQueryKind.ITEM_PERFORMANCE,
                date_from=date_from,
                date_to=date_to,
                item_metric=item_metric,
                item_query=parsed.business_query.item_query,
                limit=parsed.ranking_k,
                ranking_mode=parsed.ranking_mode or RankingMode.TOP_K,
            ),
            ranking=RankingSpec(
                mode=parsed.ranking_mode or RankingMode.TOP_K,
                k=parsed.ranking_k,
                metric_key=item_metric.value,
            ),
            reasoning_notes="Item performance request routed to SmartRest item analytics tool.",
        )

    if parsed.business_query.kind is BusinessQueryKind.CUSTOMER_SUMMARY:
        return AnalysisPlan(
            intent=AnalysisIntent.METRIC_TOTAL,
            business_query=BusinessQuerySpec(
                kind=BusinessQueryKind.CUSTOMER_SUMMARY,
                date_from=date_from,
                date_to=date_to,
            ),
            reasoning_notes="Customer request routed to SmartRest customer summary tool.",
        )

    if parsed.business_query.kind is BusinessQueryKind.RECEIPT_SUMMARY:
        return AnalysisPlan(
            intent=AnalysisIntent.METRIC_TOTAL,
            business_query=BusinessQuerySpec(
                kind=BusinessQueryKind.RECEIPT_SUMMARY,
                date_from=date_from,
                date_to=date_to,
            ),
            reasoning_notes="Receipt request routed to SmartRest receipt summary tool.",
        )

    return None


def _build_previous_period(date_from: date, date_to: date) -> tuple[date, date]:
    duration = (date_to - date_from).days + 1
    previous_end = date_from - timedelta(days=1)
    previous_start = previous_end - timedelta(days=duration - 1)
    return previous_start, previous_end


def plan_analysis(question: str) -> AnalysisPlan:
    if _is_smalltalk(question):
        return AnalysisPlan(
            intent=AnalysisIntent.SMALLTALK,
            needs_clarification=False,
            reasoning_notes="Greeting/smalltalk intent routed to conversational safe path.",
        )

    parsed = _parse_question(question)
    policy = decide_policy(parsed)

    if policy.action is ParserPolicyAction.CLARIFY:
        return AnalysisPlan(
            intent=AnalysisIntent.CLARIFY,
            needs_clarification=True,
            clarification_question=policy.clarification_question,
            reasoning_notes=policy.reasoning_notes,
        )
    if policy.action is ParserPolicyAction.REJECT:
        return AnalysisPlan(
            intent=AnalysisIntent.UNSUPPORTED,
            needs_clarification=False,
            reasoning_notes=policy.reasoning_notes,
        )

    if parsed.date_range is None:
        raise PlanningError("Policy proceed requires a parsed date range.")

    date_from, date_to = parsed.date_range.date_from, parsed.date_range.date_to
    business_plan = _build_business_plan(parsed)
    if business_plan is not None:
        return business_plan

    metric = parsed.metric
    if metric is None:
        return AnalysisPlan(
            intent=AnalysisIntent.UNSUPPORTED,
            needs_clarification=False,
            reasoning_notes="No supported SmartRest metric or business tool keyword found.",
        )

    if parsed.wants_breakdown:
        ranking_mode = parsed.ranking_mode
        ranking_k = parsed.ranking_k
        retrieval_dimension = parsed.dimension or DimensionName.SOURCE
        return AnalysisPlan(
            intent=AnalysisIntent.RANKING if ranking_mode else AnalysisIntent.BREAKDOWN,
            retrieval=RetrievalSpec(
                mode=RetrievalMode.BREAKDOWN,
                metric=metric,
                date_from=date_from,
                date_to=date_to,
                dimension=retrieval_dimension,
            ),
            ranking=(
                RankingSpec(mode=ranking_mode, k=ranking_k, metric_key=metric.value)
                if ranking_mode
                else None
            ),
            reasoning_notes=(
                "Breakdown requested by dimension; ranking applied only when "
                "explicit superlatives are present."
            ),
        )

    if parsed.wants_trend:
        return AnalysisPlan(
            intent=AnalysisIntent.TREND,
            retrieval=RetrievalSpec(
                mode=RetrievalMode.TIMESERIES,
                metric=metric,
                date_from=date_from,
                date_to=date_to,
                dimension=DimensionName.DAY,
            ),
            include_moving_average=True,
            moving_average_window=3,
            include_trend_slope=True,
            reasoning_notes=(
                "Trend intent maps to timeseries retrieval plus moving average "
                "and slope analysis."
            ),
        )

    if parsed.wants_comparison:
        previous_start, previous_end = _build_previous_period(date_from, date_to)
        metric_key = metric.value
        calculations: list[CalculationSpec] = [
            DeltaCalculationSpec(
                output_key=f"{metric_key}_delta",
                current_key=metric_key,
                previous_key=f"{metric_key}_previous",
            ),
            PercentChangeCalculationSpec(
                output_key=f"{metric_key}_percent_change",
                current_key=metric_key,
                previous_key=f"{metric_key}_previous",
            ),
        ]
        if metric is not MetricName.AVERAGE_CHECK:
            calculations.insert(
                0,
                PerDayRateCalculationSpec(
                    output_key=f"{metric_key}_per_day",
                    metric_key=metric_key,
                    day_count_key="day_count",
                ),
            )
        return AnalysisPlan(
            intent=AnalysisIntent.COMPARISON,
            retrieval=RetrievalSpec(
                mode=RetrievalMode.TOTAL,
                metric=metric,
                date_from=date_from,
                date_to=date_to,
            ),
            compare_to_previous_period=True,
            previous_period_retrieval=RetrievalSpec(
                mode=RetrievalMode.TOTAL,
                metric=metric,
                date_from=previous_start,
                date_to=previous_end,
            ),
            scalar_calculations=calculations,
            reasoning_notes=(
                "Comparison intent maps to current-period retrieval plus "
                "previous-period materialization."
            ),
        )

    total_calculations: list[CalculationSpec] = []
    if metric is not MetricName.AVERAGE_CHECK:
        total_calculations.append(
            PerDayRateCalculationSpec(
                output_key=f"{metric.value}_per_day",
                metric_key=metric.value,
                day_count_key="day_count",
            )
        )

    return AnalysisPlan(
        intent=AnalysisIntent.METRIC_TOTAL,
        retrieval=RetrievalSpec(
            mode=RetrievalMode.TOTAL,
            metric=metric,
            date_from=date_from,
            date_to=date_to,
        ),
        scalar_calculations=total_calculations,
        reasoning_notes=(
            "Plain KPI request maps to total retrieval and optional per-day "
            "normalization."
        ),
    )
