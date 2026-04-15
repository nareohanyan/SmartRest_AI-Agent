from __future__ import annotations

import re
from collections.abc import Mapping

from app.agent.parser_normalization import count_term_hits
from app.agent.planner_lexicon import PlannerLexicon
from app.schemas.analysis import DimensionName, ItemPerformanceMetric, MetricName, RankingMode

ITEM_ENTITY_TERMS = {
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
_ITEM_SINGULAR_TERMS = {
    "item",
    "dish",
    "menu item",
    "product",
    "ուտեստ",
    "ապրանք",
    "блюдо",
    "товар",
}
_ITEM_TOP_CONTEXT_TERMS = {
    "top",
    "bottom",
    "best",
    "worst",
    "performance",
    "լավագույն",
    "վատագույն",
    "топ",
}
ITEM_QUANTITY_TERMS = {
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
ITEM_REVENUE_TERMS = {
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
ITEM_DISTINCT_ORDER_TERMS = {
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
CUSTOMER_TERMS = {
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
RECEIPT_TERMS = {
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

_EN_RANKING_RE = re.compile(
    r"(?:top|bottom|best|worst|highest|lowest)\s+(\d{1,2})"
)
_HY_RANKING_RE = re.compile(r"(?:տոփ|լավագույն|վատագույն|ամենաբարձր|ամենացածր)\s+(\d{1,2})")
_RU_RANKING_RE = re.compile(
    r"(?:топ|лучш\w*|худш\w*|сам\w*\s+высок\w*|сам\w*\s+низк\w*)\s+(\d{1,2})"
)
_SINGULAR_TOP_ITEM_PATTERNS = (
    "most sold item",
    "top selling item",
    "best selling item",
    "most sold product",
    "ամենաշատ վաճառված ապրանքը",
    "ամենավաճառված ապրանքը",
    "самое продаваемое блюдо",
    "самый продаваемый товар",
)


def sales_concept_terms(lexicon: PlannerLexicon) -> set[str]:
    return {"revenue", "income", "earnings", "եկամուտ", "доход"} | lexicon.sales_metric_terms


def contains_business_signal(
    normalized_question: str,
    tokens: set[str],
    *,
    lexicon: PlannerLexicon,
) -> bool:
    high_priority_hits = count_term_hits(
        normalized_question,
        tokens,
        lexicon.high_priority_business_terms,
    )
    if high_priority_hits > 0:
        return True

    metric_hits = count_term_hits(normalized_question, tokens, lexicon.metric_terms)
    operation_hits = count_term_hits(normalized_question, tokens, lexicon.operation_terms)
    dimension_hits = count_term_hits(normalized_question, tokens, lexicon.dimension_terms)
    return metric_hits > 0 or (operation_hits > 0 and dimension_hits > 0)


def detect_metric(
    normalized_question: str,
    tokens: set[str],
    *,
    metric_alias_index: Mapping[str, str],
    lexicon: PlannerLexicon,
) -> MetricName | None:
    alias_items = sorted(metric_alias_index.items(), key=lambda item: len(item[0]), reverse=True)
    for alias, metric_id in alias_items:
        if " " in alias:
            if alias not in normalized_question:
                continue
        elif alias not in tokens:
            continue

        try:
            return MetricName(metric_id)
        except ValueError:
            continue

    if count_term_hits(normalized_question, tokens, lexicon.average_metric_terms) > 0:
        return MetricName.AVERAGE_CHECK
    if count_term_hits(normalized_question, tokens, lexicon.order_metric_terms) > 0:
        return MetricName.ORDER_COUNT
    if count_term_hits(normalized_question, tokens, sales_concept_terms(lexicon)) > 0:
        return MetricName.SALES_TOTAL
    return None


def detect_dimension(
    normalized_question: str,
    tokens: set[str],
    *,
    dimension_alias_index: Mapping[str, str],
) -> DimensionName | None:
    alias_items = sorted(dimension_alias_index.items(), key=lambda item: len(item[0]), reverse=True)
    for alias, dimension_id in alias_items:
        if " " in alias:
            if alias not in normalized_question:
                continue
        elif alias not in tokens:
            continue

        try:
            return DimensionName(dimension_id)
        except ValueError:
            continue
    return None


def needs_ranking(normalized_question: str, *, lexicon: PlannerLexicon) -> RankingMode | None:
    if any(phrase in normalized_question for phrase in lexicon.ranking_top_terms):
        return RankingMode.TOP_K
    if any(phrase in normalized_question for phrase in lexicon.ranking_bottom_terms):
        return RankingMode.BOTTOM_K
    return None


def extract_ranking_k(normalized_question: str) -> int:
    for pattern in (_EN_RANKING_RE, _HY_RANKING_RE, _RU_RANKING_RE):
        match = pattern.search(normalized_question)
        if not match:
            continue
        value = int(match.group(1))
        if 1 <= value <= 20:
            return value

    if any(pattern in normalized_question for pattern in _SINGULAR_TOP_ITEM_PATTERNS):
        return 1
    if any(term in normalized_question for term in _ITEM_SINGULAR_TERMS) and any(
        term in normalized_question
        for term in _ITEM_TOP_CONTEXT_TERMS | ITEM_QUANTITY_TERMS | ITEM_REVENUE_TERMS
    ):
        return 1
    return 3


def needs_trend(normalized_question: str, *, lexicon: PlannerLexicon) -> bool:
    return any(phrase in normalized_question for phrase in lexicon.trend_terms)


def needs_comparison(
    normalized_question: str,
    tokens: set[str],
    *,
    lexicon: PlannerLexicon,
) -> bool:
    sanitized = normalized_question
    for phrase in (
        lexicon.relative_previous_month_terms
        | lexicon.relative_last_year_terms
        | lexicon.relative_last_week_terms
    ):
        sanitized = sanitized.replace(phrase, " ")
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    sanitized_tokens = tokens if sanitized == normalized_question else set(sanitized.split())
    return (
        count_term_hits(
            sanitized,
            sanitized_tokens,
            lexicon.comparison_terms,
        )
        > 0
    )


def needs_breakdown(
    normalized_question: str,
    tokens: set[str],
    *,
    has_dimension: bool,
    lexicon: PlannerLexicon,
) -> bool:
    if any(phrase in normalized_question for phrase in lexicon.breakdown_terms):
        return True
    if not has_dimension:
        return False
    return any(token in tokens for token in ("by", "per", "ըստ", "по"))


def is_item_business_query(normalized_question: str) -> bool:
    return any(term in normalized_question for term in ITEM_ENTITY_TERMS) and any(
        term in normalized_question
        for term in _ITEM_TOP_CONTEXT_TERMS
        | ITEM_QUANTITY_TERMS
        | ITEM_REVENUE_TERMS
        | ITEM_DISTINCT_ORDER_TERMS
    )


def detect_item_metric(normalized_question: str, tokens: set[str]) -> ItemPerformanceMetric:
    if count_term_hits(normalized_question, tokens, ITEM_QUANTITY_TERMS) > 0:
        return ItemPerformanceMetric.QUANTITY_SOLD
    if count_term_hits(normalized_question, tokens, ITEM_DISTINCT_ORDER_TERMS) > 0:
        return ItemPerformanceMetric.DISTINCT_ORDERS
    if count_term_hits(normalized_question, tokens, ITEM_REVENUE_TERMS) > 0:
        return ItemPerformanceMetric.ITEM_REVENUE
    return ItemPerformanceMetric.ITEM_REVENUE


def is_customer_business_query(normalized_question: str) -> bool:
    return any(term in normalized_question for term in CUSTOMER_TERMS)


def is_receipt_business_query(normalized_question: str) -> bool:
    return any(term in normalized_question for term in RECEIPT_TERMS)
