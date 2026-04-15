from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from functools import lru_cache

from app.agent.metric_registry import get_dimension_alias_index, get_metric_alias_index
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
_SMALLTALK_TRAILING_PUNCT_RE = re.compile(r"[!?.…]+$")
_SMALLTALK_TOKEN_NORMALIZE_RE = re.compile(r"[^\w\s'’]+")
_TEXT_TOKEN_NORMALIZE_RE = re.compile(r"[^\w\s'’-]+")
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
_ARMENIAN_TOKEN_SUFFIXES = ("ս", "դ", "ը", "ն")
_ITEM_ENTITY_TERMS = {
    "item",
    "items",
    "dish",
    "dishes",
    "menu",
    "menu item",
    "product",
    "products",
    "ուտեստ",
    "մենյու",
    "ապրանք",
    "ապրանքներ",
    "блюдо",
    "блюда",
    "меню",
    "товар",
    "товары",
}
_ITEM_QUANTITY_TERMS = {
    "most sold",
    "top selling",
    "best selling",
    "most popular",
    "sold",
    "selling",
    "quantity",
    "qty",
    "popular",
    "ամենավաճառված",
    "ամենաշատ վաճառված",
    "շատ վաճառված",
    "վաճառված",
    "քանակ",
    "самое продаваемое",
    "самые продаваемые",
    "продаваем",
    "по количеству",
    "колич",
    "популяр",
}
_ITEM_REVENUE_TERMS = {
    "highest revenue",
    "top revenue",
    "most revenue",
    "highest grossing",
    "revenue",
    "sales value",
    "item revenue",
    "ամենաեկամտաբեր",
    "ամենաշատ եկամուտ",
    "եկամտաբեր",
    "եկամուտ",
    "высокая выручка",
    "по выручке",
    "выруч",
    "доход",
    "прибыл",
}
_ITEM_DISTINCT_ORDER_TERMS = {
    "distinct orders",
    "order presence",
    "most ordered",
    "by orders",
    "պատվեր",
    "պատվերներով",
    "заказ",
    "заказы",
    "по заказам",
}
_SALES_CONCEPT_TERMS = {"revenue", "income", "earnings", "եկամուտ", "доход"} | (
    _PLANNER_LEXICON.sales_metric_terms
)


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
        if term in tokens or any(token.startswith(term) for token in tokens):
            hits += 1
    return hits


@lru_cache(maxsize=1)
def _semantic_base_tokens() -> frozenset[str]:
    base_terms: set[str] = set()
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
        _ITEM_ENTITY_TERMS,
        _ITEM_QUANTITY_TERMS,
        _ITEM_REVENUE_TERMS,
        _ITEM_DISTINCT_ORDER_TERMS,
        _SALES_CONCEPT_TERMS,
    )
    for field in lexicon_fields:
        base_terms.update(term for term in field if " " not in term)
    base_terms.update(alias for alias in get_metric_alias_index() if " " not in alias)
    base_terms.update(alias for alias in get_dimension_alias_index() if " " not in alias)
    return frozenset(base_terms)


def _semantic_token_candidates(token: str) -> set[str]:
    candidates = {token}
    if _ARMENIAN_CHAR_RE.search(token) is None:
        return candidates

    for suffix in _ARMENIAN_TOKEN_SUFFIXES:
        if not token.endswith(suffix):
            continue
        if len(token) <= len(suffix) + 1:
            continue
        stripped = token[: -len(suffix)]
        if stripped in _semantic_base_tokens():
            candidates.add(stripped)
    return candidates


def _semantic_tokens(normalized_question: str) -> set[str]:
    tokens: set[str] = set()
    for token in normalized_question.split():
        tokens.update(_semantic_token_candidates(token))
    return tokens


def _contains_business_signal(normalized_question: str) -> bool:
    tokens = _semantic_tokens(normalized_question)
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
    normalized = _normalize_text(question)
    tokens = _semantic_tokens(normalized)
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

    if _count_term_hits(normalized, tokens, _PLANNER_LEXICON.average_metric_terms) > 0:
        return MetricName.AVERAGE_CHECK
    if _count_term_hits(normalized, tokens, _PLANNER_LEXICON.order_metric_terms) > 0:
        return MetricName.ORDER_COUNT
    if _count_term_hits(normalized, tokens, _SALES_CONCEPT_TERMS) > 0:
        return MetricName.SALES_TOTAL
    return None


def _detect_dimension(question: str) -> DimensionName | None:
    normalized = _normalize_text(question)
    tokens = _semantic_tokens(normalized)
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
    tokens = _semantic_tokens(normalized)
    return any(token in tokens for token in ("by", "per", "ըստ", "по"))


def _extract_ranking_k(question: str) -> int:
    normalized = _normalize_text(question)
    patterns = [
        r"(?:top|bottom|best|worst|highest|lowest)\s+(\d{1,2})",
        r"(?:տոփ|լավագույն|վատագույն|ամենաբարձր|ամենացածր)\s+(\d{1,2})",
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
    sanitized = normalized
    for phrase in (
        _PLANNER_LEXICON.relative_previous_month_terms
        | _PLANNER_LEXICON.relative_last_year_terms
        | _PLANNER_LEXICON.relative_last_week_terms
    ):
        sanitized = sanitized.replace(phrase, " ")
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return (
        _count_term_hits(
            sanitized,
            _semantic_tokens(sanitized),
            _PLANNER_LEXICON.comparison_terms,
        )
        > 0
    )


def _is_item_business_query(question: str) -> bool:
    normalized = _normalize_text(question)
    performance_terms = {
        "top",
        "bottom",
        "best",
        "worst",
        "performance",
        "լավագույն",
        "վատագույն",
        "топ",
    }
    return any(term in normalized for term in _ITEM_ENTITY_TERMS) and any(
        term in normalized for term in performance_terms
        | _ITEM_QUANTITY_TERMS
        | _ITEM_REVENUE_TERMS
        | _ITEM_DISTINCT_ORDER_TERMS
    )


def _is_customer_business_query(question: str) -> bool:
    normalized = _normalize_text(question)
    customer_terms = {
        "customer",
        "customers",
        "client",
        "clients",
        "guest",
        "guests",
        "հաճախորդ",
        "հաճախորդներ",
        "клиент",
        "клиенты",
        "гость",
        "гости",
    }
    return any(term in normalized for term in customer_terms)


def _is_receipt_business_query(question: str) -> bool:
    normalized = _normalize_text(question)
    receipt_terms = {
        "receipt",
        "receipts",
        "fiscal",
        "check",
        "checks",
        "receipt status",
        "կտրոն",
        "ֆիսկալ",
        "чек",
        "чеки",
        "фискаль",
    }
    return any(term in normalized for term in receipt_terms)


def _detect_item_metric(question: str) -> ItemPerformanceMetric:
    normalized = _normalize_text(question)
    tokens = _semantic_tokens(normalized)
    if _count_term_hits(normalized, tokens, _ITEM_QUANTITY_TERMS) > 0:
        return ItemPerformanceMetric.QUANTITY_SOLD
    if _count_term_hits(normalized, tokens, _ITEM_DISTINCT_ORDER_TERMS) > 0:
        return ItemPerformanceMetric.DISTINCT_ORDERS
    if _count_term_hits(normalized, tokens, _ITEM_REVENUE_TERMS) > 0:
        return ItemPerformanceMetric.ITEM_REVENUE
    return ItemPerformanceMetric.ITEM_REVENUE


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


def _build_business_plan(question: str, date_from: date, date_to: date) -> AnalysisPlan | None:
    ranking_mode = _needs_ranking(question) or RankingMode.TOP_K
    ranking_k = _extract_ranking_k(question)

    if _is_item_business_query(question):
        return AnalysisPlan(
            intent=AnalysisIntent.RANKING,
            business_query=BusinessQuerySpec(
                kind=BusinessQueryKind.ITEM_PERFORMANCE,
                date_from=date_from,
                date_to=date_to,
                item_metric=_detect_item_metric(question),
                item_query=_extract_item_query(question),
                limit=ranking_k,
                ranking_mode=ranking_mode,
            ),
            ranking=RankingSpec(
                mode=ranking_mode,
                k=ranking_k,
                metric_key=_detect_item_metric(question).value,
            ),
            reasoning_notes="Item performance request routed to SmartRest item analytics tool.",
        )

    if _is_customer_business_query(question):
        return AnalysisPlan(
            intent=AnalysisIntent.METRIC_TOTAL,
            business_query=BusinessQuerySpec(
                kind=BusinessQueryKind.CUSTOMER_SUMMARY,
                date_from=date_from,
                date_to=date_to,
            ),
            reasoning_notes="Customer request routed to SmartRest customer summary tool.",
        )

    if _is_receipt_business_query(question):
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

    normalized = _normalize_text(question)
    date_range = _parse_date_range(question)
    if date_range is None:
        if not _contains_business_signal(normalized):
            return AnalysisPlan(
                intent=AnalysisIntent.UNSUPPORTED,
                needs_clarification=False,
                reasoning_notes="No supported SmartRest metric or business tool keyword found.",
            )
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
    business_plan = _build_business_plan(question, date_from, date_to)
    if business_plan is not None:
        return business_plan

    metric = _detect_metric(question)
    if metric is None:
        return AnalysisPlan(
            intent=AnalysisIntent.UNSUPPORTED,
            needs_clarification=False,
            reasoning_notes="No supported SmartRest metric or business tool keyword found.",
        )

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
