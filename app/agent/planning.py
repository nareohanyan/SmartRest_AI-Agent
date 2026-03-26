from __future__ import annotations

import re
from datetime import date, timedelta

from app.agent.metric_registry import get_dimension_alias_index, get_metric_alias_index
from app.agent.planner_lexicon import get_planner_lexicon
from app.schemas.analysis import (
    AnalysisIntent,
    AnalysisPlan,
    DimensionName,
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
_SMALLTALK_TRAILING_PUNCT_RE = re.compile(r"[!?.…]+$")
_SMALLTALK_TOKEN_NORMALIZE_RE = re.compile(r"[^\w\s'’]+")
_TEXT_TOKEN_NORMALIZE_RE = re.compile(r"[^\w\s'’-]+")
_MULTI_TASK_SPLIT_RE = re.compile(r"\s+(?:and|և|и)\s+", re.IGNORECASE)
_PLANNER_LEXICON = get_planner_lexicon()


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


def _normalize_text(question: str) -> str:
    normalized = question.lower().strip().replace("’", "'")
    normalized = _TEXT_TOKEN_NORMALIZE_RE.sub(" ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _normalize_smalltalk_text(question: str) -> str:
    normalized = question.lower().strip()
    normalized = normalized.replace("’", "'")
    normalized = _SMALLTALK_TRAILING_PUNCT_RE.sub("", normalized)
    normalized = _SMALLTALK_TOKEN_NORMALIZE_RE.sub(" ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _count_term_hits(normalized_question: str, tokens: set[str], terms: set[str]) -> int:
    hits = 0
    for term in terms:
        if " " in term:
            if term in normalized_question:
                hits += 1
            continue
        if term in tokens:
            hits += 1
    return hits


def _contains_business_signal(normalized_question: str) -> bool:
    tokens = set(normalized_question.split())
    high_priority_hits = _count_term_hits(
        normalized_question,
        tokens,
        _PLANNER_LEXICON.high_priority_business_terms,
    )
    if high_priority_hits > 0:
        return True

    metric_hits = _count_term_hits(normalized_question, tokens, _PLANNER_LEXICON.metric_terms)
    operation_hits = _count_term_hits(
        normalized_question,
        tokens,
        _PLANNER_LEXICON.operation_terms,
    )
    dimension_hits = _count_term_hits(
        normalized_question,
        tokens,
        _PLANNER_LEXICON.dimension_terms,
    )

    if metric_hits > 0:
        return True
    if operation_hits > 0 and dimension_hits > 0:
        return True
    return False


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
    normalized = _normalize_text(question)
    if not normalized:
        return None

    today = reference_date or date.today()
    yesterday = today - timedelta(days=1)
    last_week_start = today - timedelta(days=7)
    last_week_end = today - timedelta(days=1)
    month_start = today.replace(day=1)
    past_30_days_start = today - timedelta(days=29)

    matches: list[tuple[date, date]] = []
    if _has_any_phrase(normalized, _PLANNER_LEXICON.relative_today_terms):
        matches.append((today, today))
    if _has_any_phrase(normalized, _PLANNER_LEXICON.relative_yesterday_terms):
        matches.append((yesterday, yesterday))
    if _has_any_phrase(normalized, _PLANNER_LEXICON.relative_last_week_terms):
        matches.append((last_week_start, last_week_end))
    if _has_any_phrase(normalized, _PLANNER_LEXICON.relative_this_month_terms):
        matches.append((month_start, today))
    if _has_any_phrase(normalized, _PLANNER_LEXICON.relative_past_30_days_terms):
        matches.append((past_30_days_start, today))

    if len(matches) == 1:
        return matches[0]
    return None


def _detect_metric(question: str) -> MetricName | None:
    normalized = _normalize_text(question)

    tokens = set(normalized.split())
    alias_items = sorted(
        get_metric_alias_index().items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for alias, metric_id in alias_items:
        if " " in alias:
            if alias not in normalized:
                continue
        elif alias not in tokens:
            continue

        try:
            return MetricName(metric_id)
        except ValueError:
            continue

    if _has_any_phrase(normalized, _PLANNER_LEXICON.average_metric_terms):
        return MetricName.AVERAGE_CHECK
    if _has_any_phrase(normalized, _PLANNER_LEXICON.order_metric_terms):
        return MetricName.ORDER_COUNT
    if _has_any_phrase(normalized, _PLANNER_LEXICON.sales_metric_terms):
        return MetricName.SALES_TOTAL
    return None


def _detect_dimension(question: str) -> DimensionName | None:
    normalized = _normalize_text(question)
    tokens = set(normalized.split())
    alias_items = sorted(
        get_dimension_alias_index().items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    for alias, dimension_id in alias_items:
        if " " in alias:
            if alias not in normalized:
                continue
        elif alias not in tokens:
            continue

        try:
            return DimensionName(dimension_id)
        except ValueError:
            continue
    return None


def _map_metric_to_legacy_report(metric: MetricName) -> ReportType | None:
    if metric is MetricName.SALES_TOTAL:
        return ReportType.SALES_TOTAL
    if metric is MetricName.ORDER_COUNT:
        return ReportType.ORDER_COUNT
    if metric is MetricName.AVERAGE_CHECK:
        return ReportType.AVERAGE_CHECK
    return None


def plan_legacy_tasks(question: str) -> list[LegacyReportTask] | None:
    normalized = _normalize_text(question)
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
    normalized = _normalize_text(question)
    if _has_any_phrase(normalized, _PLANNER_LEXICON.breakdown_terms):
        return True
    if _detect_dimension(question) is None:
        return False
    return any(token in normalized.split() for token in ("by", "per", "ըստ", "по"))


def _extract_ranking_k(question: str) -> int:
    normalized = _normalize_text(question)
    patterns = [
        r"(?:top|bottom|best|worst|highest|lowest)\s+(\d{1,2})",
        r"(?:լավագույն|վատագույն|ամենաբարձր|ամենացածր)\s+(\d{1,2})",
        r"(?:топ|лучш\w*|худш\w*|сам\w*\s+высок\w*|сам\w*\s+низк\w*)\s+(\d{1,2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        value = int(match.group(1))
        if 1 <= value <= 20:
            return value
    return 3


def _needs_ranking(question: str) -> RankingMode | None:
    normalized = _normalize_text(question)
    if _has_any_phrase(normalized, _PLANNER_LEXICON.ranking_top_terms):
        return RankingMode.TOP_K
    if _has_any_phrase(normalized, _PLANNER_LEXICON.ranking_bottom_terms):
        return RankingMode.BOTTOM_K
    return None


def _needs_trend(question: str) -> bool:
    normalized = _normalize_text(question)
    return _has_any_phrase(normalized, _PLANNER_LEXICON.trend_terms)


def _needs_comparison(question: str) -> bool:
    normalized = _normalize_text(question)
    return _has_any_phrase(normalized, _PLANNER_LEXICON.comparison_terms)


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

    metric = _detect_metric(question)
    if metric is None:
        return AnalysisPlan(
            intent=AnalysisIntent.UNSUPPORTED,
            needs_clarification=False,
            reasoning_notes="No supported demo metric keyword found.",
        )

    date_range = _parse_date_range(question)
    if date_range is None:
        language = _question_language(question)
        clarification_question = (
            "Խնդրում եմ նշեք ժամանակահատվածը YYYY-MM-DD to YYYY-MM-DD ձևաչափով:"
            if language == "hy"
            else (
                "Пожалуйста, укажите диапазон дат в формате YYYY-MM-DD to YYYY-MM-DD."
                if language == "ru"
                else "Please provide a date range in YYYY-MM-DD to YYYY-MM-DD format."
            )
        )
        return AnalysisPlan(
            intent=AnalysisIntent.CLARIFY,
            needs_clarification=True,
            clarification_question=clarification_question,
            reasoning_notes="Supported demo planning requires an explicit date range.",
        )

    date_from, date_to = date_range
    if _needs_breakdown(question):
        ranking_mode = _needs_ranking(question)
        ranking_k = _extract_ranking_k(question)
        requested_dimension = _detect_dimension(question)
        retrieval_dimension = requested_dimension or DimensionName.SOURCE
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

    if _needs_trend(question):
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

    if _needs_comparison(question):
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
