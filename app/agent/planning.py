"""Deterministic semantic planner for demo-friendly dynamic analysis.

This planner intentionally uses a narrow, testable rule set. It is not trying to
be a general LLM substitute; it gives the demo a professional contract that can
later be replaced by an LLM-backed planner without changing the downstream tool
interfaces.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from app.schemas.analysis import (
    AnalysisIntent,
    AnalysisPlan,
    DimensionName,
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

_DATE_RANGE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*(?:to|-)\s*(\d{4}-\d{2}-\d{2})")
_ARMENIAN_CHAR_RE = re.compile(r"[\u0531-\u058F]")
_SMALLTALK_TRAILING_PUNCT_RE = re.compile(r"[!?.…]+$")
_SMALLTALK_TOKEN_NORMALIZE_RE = re.compile(r"[^\w\s'’]+")

_PURE_SMALLTALK_PHRASES = {
    "hi",
    "hello",
    "hey",
    "hello there",
    "good day",
    "good morning",
    "good afternoon",
    "good evening",
    "how are you",
    "how you doing",
    "what you're up to",
    "what youre up to",
    "what's up",
    "whats up",
    "hello what's up",
    "hello whats up",
    "hi what's up",
    "hi whats up",
    "hey what's up",
    "hey whats up",
    "բարև",
    "բարեւ",
    "բարև ձեզ",
    "բարեւ ձեզ",
    "barev",
    "ողջույն",
    "voghjuyn",
    "բարի օր",
    "բարի լույս",
    "բարի երեկո",
    "ինչպես ես",
    "ինչ կա",
    "ոնց ես",
    "inchpes es",
    "привет",
    "privet",
    "здравствуйте",
    "здраствуйте",
    "zdravstvuyte",
    "zdrastvuyte",
    "доброе утро",
    "добрый день",
    "добрый вечер",
    "как дела",
    "как ты",
    "что нового",
    "kak dela",
}

_GREETING_TOKENS = {
    "hi",
    "hello",
    "hey",
    "բարև",
    "բարեւ",
    "barev",
    "ողջույն",
    "voghjuyn",
    "привет",
    "privet",
    "здравствуйте",
    "здраствуйте",
    "zdravstvuyte",
    "zdrastvuyte",
    "բարի",
    "good",
    "добрый",
    "доброе",
}

_SMALLTALK_SUPPORT_TOKENS = {
    "there",
    "what's",
    "whats",
    "up",
    "how",
    "are",
    "you",
    "doing",
    "what",
    "you're",
    "youre",
    "to",
    "good",
    "morning",
    "afternoon",
    "evening",
    "ինչպես",
    "ես",
    "inchpes",
    "բարի",
    "լույս",
    "երեկո",
    "как",
    "дела",
    "доброе",
    "утро",
    "добрый",
    "день",
    "вечер",
    "как",
    "ты",
    "что",
    "нового",
    "ոնց",
    "կա",
}

_METRIC_TERMS = {
    "վաճառք",
    "շահույթ",
    "եկամուտ",
    "միջինում",
    "հաշվետվություն",
    "ծախս",
    "վնաս",
    "օգուտ",
    "եկամտաբեր",
    "շահավետ",
    "օգտակար",
    "պատվեր",
    "продажи",
    "прибыль",
    "доход",
    "средний",
    "отчет",
    "расходы",
    "убыток",
    "выгода",
    "прибыльный",
    "полезный",
    "заказ",
    "sales",
    "profit",
    "income",
    "average",
    "report",
    "expense",
    "loss",
    "benefit",
    "profitable",
    "useful",
    "order",
    "earnings",
}

_HIGH_PRIORITY_BUSINESS_TERMS = {
    "հաշվետվություն",
    "վաճառք",
    "օգուտ",
    "շահույթ",
    "отчет",
    "продажи",
    "прибыль",
    "доход",
    "report",
    "sales",
    "profit",
    "earnings",
}

_OPERATION_TERMS = {
    "համեմաել",
    "աճ",
    "նվազել",
    "հաշվարկել",
    "сравнивать",
    "увеличивать",
    "уменьшать",
    "вычислять",
    "compare",
    "increase",
    "decrease",
    "calculate",
}

_DIMENSION_TERMS = {
    "մասնաճյուղ",
    "ֆիլիալ",
    "հասցե",
    "բաժին",
    "филиал",
    "дочерняя компания",
    "адрес",
    "отдел",
    "branch",
    "subsidiary",
    "address",
    "department",
}


class PlanningError(ValueError):
    """Raised when a request cannot be planned safely."""


def _is_armenian_text(text: str) -> bool:
    return _ARMENIAN_CHAR_RE.search(text) is not None


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
        _HIGH_PRIORITY_BUSINESS_TERMS,
    )
    if high_priority_hits > 0:
        return True

    metric_hits = _count_term_hits(normalized_question, tokens, _METRIC_TERMS)
    operation_hits = _count_term_hits(normalized_question, tokens, _OPERATION_TERMS)
    dimension_hits = _count_term_hits(normalized_question, tokens, _DIMENSION_TERMS)

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

    if normalized in _PURE_SMALLTALK_PHRASES:
        return True

    tokens = normalized.split()
    if not tokens or len(tokens) > 7:
        return False

    if not any(token in _GREETING_TOKENS for token in tokens):
        return False

    allowed_tokens = _GREETING_TOKENS | _SMALLTALK_SUPPORT_TOKENS
    return all(token in allowed_tokens for token in tokens)


def _parse_date_range(question: str) -> tuple[date, date] | None:
    match = _DATE_RANGE_RE.search(question)
    if not match:
        return None
    return (date.fromisoformat(match.group(1)), date.fromisoformat(match.group(2)))


def _detect_metric(question: str) -> MetricName | None:
    lowered = question.lower()
    if "average check" in lowered or "avg check" in lowered:
        return MetricName.AVERAGE_CHECK
    if "order" in lowered:
        return MetricName.ORDER_COUNT
    if "sales" in lowered or "revenue" in lowered:
        return MetricName.SALES_TOTAL
    return None


def _needs_breakdown(question: str) -> bool:
    lowered = question.lower()
    return "by source" in lowered or "per source" in lowered or "sources" in lowered


def _needs_ranking(question: str) -> RankingMode | None:
    lowered = question.lower()
    if any(token in lowered for token in ["top", "highest", "best", "most"]):
        return RankingMode.TOP_K
    if any(token in lowered for token in ["bottom", "lowest", "worst", "least"]):
        return RankingMode.BOTTOM_K
    return None


def _needs_trend(question: str) -> bool:
    lowered = question.lower()
    return any(
        token in lowered for token in ["trend", "trending", "over time", "daily", "per day"]
    )


def _needs_comparison(question: str) -> bool:
    lowered = question.lower()
    return any(
        token in lowered for token in ["compare", "compared", "change", "growth", "vs"]
    )


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
        clarification_question = (
            "Խնդրում եմ նշեք ժամանակահատվածը YYYY-MM-DD to YYYY-MM-DD ձևաչափով:"
            if _is_armenian_text(question)
            else "Please provide a date range in YYYY-MM-DD to YYYY-MM-DD format."
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
        return AnalysisPlan(
            intent=AnalysisIntent.RANKING if ranking_mode else AnalysisIntent.BREAKDOWN,
            retrieval=RetrievalSpec(
                mode=RetrievalMode.BREAKDOWN,
                metric=metric,
                date_from=date_from,
                date_to=date_to,
                dimension=DimensionName.SOURCE,
            ),
            ranking=(
                RankingSpec(mode=ranking_mode, k=3, metric_key=metric.value)
                if ranking_mode
                else None
            ),
            reasoning_notes=(
                "Breakdown requested by source; ranking applied only when "
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
