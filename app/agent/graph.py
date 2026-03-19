"""Minimal LangGraph workflow for Task 9."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from langgraph.graph import END, StateGraph

from app.agent.calc_policy import select_calculation_specs
from app.agent.calc_tools import compute_metrics_tool
from app.agent.llm import (
    CLARIFICATION_FALLBACK_QUESTION,
    InterpretationContractError,
    LLMClientError,
    build_interpret_request_messages,
    get_llm_client,
    parse_interpretation_output_json,
    validate_interpretation_output,
)
from app.agent.metrics_mapper import map_report_response_to_base_metrics
from app.agent.report_tools import resolve_scope_tool, run_report_tool
from app.persistence.runtime_persistence import RuntimePersistenceService
from app.schemas.agent import AgentState, IntentType, LLMErrorCategory, RunStatus
from app.schemas.calculations import ComputeMetricsRequest
from app.schemas.reports import ReportFilters, ReportRequest, ReportType
from app.schemas.tools import AccessStatus, RunReportRequest

_DATE_RANGE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})")
_AUTHORIZATION_BLOCKED_WARNING = "authorization_blocked_report_not_allowed"
_INTERPRET_RATE_LIMIT_FALLBACK_WARNING = "interpretation_rate_limit_fallback"
_MAX_MULTI_REPORTS = 3
_DEFAULT_CLARIFICATION_QUESTIONS = {
    CLARIFICATION_FALLBACK_QUESTION,
    "Please provide a date range using YYYY-MM-DD to YYYY-MM-DD.",
    (
        "Please provide a date range (YYYY-MM-DD to YYYY-MM-DD) "
        "or a relative period like today / last week / last 3 months."
    ),
    "Please clarify your request by providing a date range.",
}

_LOCALIZED_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "access_denied_missing_scope": "Access denied: missing scope request.",
        "clarify_need_date_range": (
            "Please provide a date range (YYYY-MM-DD to YYYY-MM-DD) "
            "or a relative period like today, last week, or last 3 months."
        ),
        "unsupported_request": (
            "Unsupported request. Supported scopes include sales, sources, couriers, "
            "customers, locations, delivery fees, payments, balances, weekday and daily trends, "
            "and gross-profit analytics."
        ),
        "small_talk_response": (
            "Hi. I can help with restaurant analytics. "
            "Ask about sales, orders, customers, locations, payments, or trends."
        ),
        "access_denied_request": "Access denied for this request.",
        "run_failed_internal": "Run failed due to internal processing error.",
        "run_failed_missing_context": "Run failed: missing required report execution context.",
        "run_failed_execution_error": "Run failed: report execution error.",
        "calc_missing_report_output": "Calculation failed: report output is missing.",
        "calc_mapping_failed": "Calculation failed: unable to map report metrics.",
        "reason_missing_tool_output": "Reasoning failed: report output is missing.",
        "compose_missing_tool_output": "Compose failed: report output is missing.",
        "report_summary": "Report {report} for {date_from} to {date_to}: {metrics}.",
        "multi_report_header": "Multi-report response:",
        "derived_prefix": " Derived metrics: {derived}.",
        "not_available": "n/a",
    },
    "hy": {
        "access_denied_missing_scope": "Մուտքը մերժված է՝ scope request-ը բացակայում է։",
        "clarify_need_date_range": "Նշեք ամսաթվերի միջակայք՝ YYYY-MM-DD to YYYY-MM-DD ձևաչափով։",
        "unsupported_request": (
            "Չաջակցվող հարցում։ Աջակցվում են վաճառք, աղբյուրներ, առաքիչներ, "
            "հաճախորդներ, հասցեներ, առաքման վճար, վճարումներ, մնացորդ, "
            "օրական և շաբաթվա տրենդեր, ինչպես նաև համախառն շահույթի վերլուծություն։"
        ),
        "small_talk_response": (
            "Բարև։ Կարող եմ օգնել ռեստորանի վերլուծություններով։ "
            "Հարցրեք վաճառքի, պատվերների, հաճախորդների, հասցեների, վճարումների կամ տրենդերի մասին։"
        ),
        "access_denied_request": "Այս հարցման համար մուտքը մերժված է։",
        "run_failed_internal": "Կատարման ձախողում՝ ներքին սխալի պատճառով։",
        "run_failed_missing_context": "Կատարման ձախողում՝ բացակայում է պարտադիր համատեքստը։",
        "run_failed_execution_error": "Կատարման ձախողում՝ հաշվետվության կատարման սխալ։",
        "calc_missing_report_output": "Հաշվարկը ձախողվեց՝ հաշվետվության արդյունքը բացակայում է։",
        "calc_mapping_failed": "Հաշվարկը ձախողվեց՝ մետրիկաների քարտեզագրումը չհաջողվեց։",
        "reason_missing_tool_output": (
            "Վերլուծությունը ձախողվեց՝ հաշվետվության արդյունքը բացակայում է։"
        ),
        "compose_missing_tool_output": (
            "Պատասխանի կազմումը ձախողվեց՝ հաշվետվության արդյունքը բացակայում է։"
        ),
        "report_summary": "Հաշվետվություն {report}՝ {date_from}-ից {date_to}: {metrics}։",
        "multi_report_header": "Բազմահաշվետվական պատասխան՝",
        "derived_prefix": "մետրիկաներ՝ {derived}։",
        "not_available": "հասանելի չէ",
    },
    "ru": {
        "access_denied_missing_scope": "Доступ запрещен: отсутствует scope request.",
        "clarify_need_date_range": (
            "Укажите диапазон дат в формате YYYY-MM-DD to YYYY-MM-DD "
            "или относительный период (сегодня, прошлая неделя, последние 3 месяца)."
        ),
        "unsupported_request": (
            "Неподдерживаемый запрос. Поддерживаются аналитика продаж, источников, "
            "курьеров, клиентов, локаций, доставки, оплат, задолженности, "
            "дневных/недельных трендов и валовой прибыли."
        ),
        "small_talk_response": (
            "Привет. Я могу помочь с аналитикой ресторана. "
            "Спросите про продажи, заказы, клиентов, локации, оплаты или тренды."
        ),
        "access_denied_request": "Доступ к этому запросу запрещен.",
        "run_failed_internal": "Выполнение не удалось из-за внутренней ошибки.",
        "run_failed_missing_context": "Выполнение не удалось: отсутствует обязательный контекст.",
        "run_failed_execution_error": "Выполнение не удалось: ошибка выполнения отчета.",
        "calc_missing_report_output": "Расчет не выполнен: отсутствует результат отчета.",
        "calc_mapping_failed": "Расчет не выполнен: не удалось сопоставить метрики отчета.",
        "reason_missing_tool_output": "Анализ не выполнен: отсутствует результат отчета.",
        "compose_missing_tool_output": (
            "Формирование ответа не выполнено: отсутствует результат отчета."
        ),
        "report_summary": "Отчет {report} за период {date_from} - {date_to}: {metrics}.",
        "multi_report_header": "Ответ по нескольким отчетам:",
        "derived_prefix": " Производные метрики: {derived}.",
        "not_available": "н/д",
    },
}

_BREAKDOWN_REPORT_IDS = {
    ReportType.SALES_BY_SOURCE,
    ReportType.SALES_BY_COURIER,
    ReportType.TOP_LOCATIONS,
    ReportType.TOP_CUSTOMERS,
    ReportType.DAILY_SALES_TREND,
    ReportType.DAILY_ORDER_TREND,
    ReportType.SALES_BY_WEEKDAY,
}

_TOP_N_DISPLAY_REPORT_IDS = {
    ReportType.SALES_BY_SOURCE,
    ReportType.SALES_BY_COURIER,
    ReportType.TOP_LOCATIONS,
    ReportType.TOP_CUSTOMERS,
}

_LOCALIZED_REPORT_NAMES: dict[str, dict[str, str]] = {
    "en": {
        "sales_total": "sales_total",
        "order_count": "order_count",
        "average_check": "average_check",
        "sales_by_source": "sales_by_source",
        "sales_by_courier": "sales_by_courier",
        "top_locations": "top_locations",
        "top_customers": "top_customers",
        "repeat_customer_rate": "repeat_customer_rate",
        "delivery_fee_analytics": "delivery_fee_analytics",
        "payment_collection": "payment_collection",
        "outstanding_balance": "outstanding_balance",
        "daily_sales_trend": "daily_sales_trend",
        "daily_order_trend": "daily_order_trend",
        "sales_by_weekday": "sales_by_weekday",
        "gross_profit": "gross_profit",
        "location_concentration": "location_concentration",
    },
    "hy": {
        "sales_total": "ընդհանուր վաճառք",
        "order_count": "պատվերների քանակ",
        "average_check": "միջին չեկ",
        "sales_by_source": "վաճառք ըստ աղբյուրի",
        "sales_by_courier": "վաճառք ըստ առաքիչի",
        "top_locations": "առավել ակտիվ հասցեներ",
        "top_customers": "առավել ակտիվ հաճախորդներ",
        "repeat_customer_rate": "կրկնվող հաճախորդների տոկոս",
        "delivery_fee_analytics": "առաքման վճարի վերլուծություն",
        "payment_collection": "վճարումների հավաքագրում",
        "outstanding_balance": "չմարված մնացորդ",
        "daily_sales_trend": "օրական վաճառքի դինամիկա",
        "daily_order_trend": "օրական պատվերների դինամիկա",
        "sales_by_weekday": "վաճառք ըստ շաբաթվա օրվա",
        "gross_profit": "համախառն շահույթ",
        "location_concentration": "հասցեների կենտրոնացում",
    },
    "ru": {
        "sales_total": "общие продажи",
        "order_count": "количество заказов",
        "average_check": "средний чек",
        "sales_by_source": "продажи по источнику",
        "sales_by_courier": "продажи по курьеру",
        "top_locations": "топ локаций",
        "top_customers": "топ клиентов",
        "repeat_customer_rate": "доля повторных клиентов",
        "delivery_fee_analytics": "аналитика стоимости доставки",
        "payment_collection": "собираемость оплат",
        "outstanding_balance": "задолженность",
        "daily_sales_trend": "ежедневный тренд продаж",
        "daily_order_trend": "ежедневный тренд заказов",
        "sales_by_weekday": "продажи по дням недели",
        "gross_profit": "валовая прибыль",
        "location_concentration": "концентрация локаций",
    },
}

_LOCALIZED_METRIC_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "sales_total": "sales_total",
        "order_count": "order_count",
        "average_check": "average_check",
        "sales_total_per_day": "sales_total_per_day",
        "delivery_fee_total": "delivery_fee_total",
        "delivery_fee_average": "delivery_fee_average",
        "collection_rate_percent": "collection_rate_percent",
        "outstanding_balance": "outstanding_balance",
        "gross_profit": "gross_profit",
        "gross_margin_percent": "gross_margin_percent",
        "repeat_customer_rate_percent": "repeat_customer_rate_percent",
        "repeat_customer_count": "repeat_customer_count",
    },
    "hy": {
        "sales_total": "ընդհանուր վաճառք",
        "order_count": "պատվերների քանակ",
        "average_check": "միջին չեկ",
        "sales_total_per_day": "օրական միջին վաճառք",
        "delivery_fee_total": "առաքման վճար (ընդհանուր)",
        "delivery_fee_average": "առաքման միջին վճար",
        "collection_rate_percent": "հավաքագրման տոկոս",
        "outstanding_balance": "չմարված մնացորդ",
        "gross_profit": "համախառն շահույթ",
        "gross_margin_percent": "համախառն մարժա (%)",
        "repeat_customer_rate_percent": "կրկնվող հաճախորդների տոկոս",
        "repeat_customer_count": "կրկնվող հաճախորդների քանակ",
    },
    "ru": {
        "sales_total": "общие продажи",
        "order_count": "количество заказов",
        "average_check": "средний чек",
        "sales_total_per_day": "продажи в день",
        "delivery_fee_total": "стоимость доставки (итого)",
        "delivery_fee_average": "средняя стоимость доставки",
        "collection_rate_percent": "процент собираемости",
        "outstanding_balance": "задолженность",
        "gross_profit": "валовая прибыль",
        "gross_margin_percent": "валовая маржа (%)",
        "repeat_customer_rate_percent": "доля повторных клиентов",
        "repeat_customer_count": "число повторных клиентов",
    },
}


def _response_language(question: str) -> str:
    if re.search(r"[\u0531-\u0556\u0561-\u0587]", question):
        return "hy"
    if re.search(r"[\u0400-\u04FF]", question):
        return "ru"
    return "en"


def _localized_message(state: AgentState, key: str, **kwargs: Any) -> str:
    language = _response_language(state.user_question)
    template = _LOCALIZED_MESSAGES[language][key]
    return template.format(**kwargs)


def _localized_clarification_question(state: AgentState) -> str:
    question = (state.clarification_question or "").strip()
    if question and question not in _DEFAULT_CLARIFICATION_QUESTIONS:
        return question
    return _localized_message(state, "clarify_need_date_range")


def _localized_report_name(state: AgentState, report_id: ReportType) -> str:
    language = _response_language(state.user_question)
    return _LOCALIZED_REPORT_NAMES[language].get(report_id.value, report_id.value)


def _localized_metric_label(state: AgentState, label: str) -> str:
    language = _response_language(state.user_question)
    return _LOCALIZED_METRIC_LABELS[language].get(label, label)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


@dataclass(frozen=True)
class QuerySlots:
    top_n: int | None = None
    group_by: str | None = None
    metric: str | None = None
    entity: str | None = None
    source: str | None = None


def _extract_top_n(question: str) -> int | None:
    patterns = (
        r"\btop\s*(\d{1,2})\b",
        r"\bтоп[-\s]?(\d{1,2})\b",
        r"\bթոփ\s*(\d{1,2})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, question, re.IGNORECASE)
        if match is None:
            continue
        value = int(match.group(1))
        if 1 <= value <= 50:
            return value
    return None


def _extract_group_by(question: str) -> str | None:
    text = question.lower()
    if _contains_any(text, ("by source", "source mix", "по источ", "ըստ աղբյուր")):
        return "source"
    if _contains_any(text, ("by courier", "курьер", "ըստ առաքիչ")):
        return "courier"
    if _contains_any(text, ("by weekday", "day of week", "дням недели", "շաբաթվա օր")):
        return "weekday"
    if _contains_any(text, ("by address", "top address", "топ адрес", "ըստ հասցե")):
        return "location"
    if _contains_any(text, ("by customer", "топ клиент", "ըստ հաճախորդ")):
        return "customer"
    return None


def _extract_metric(question: str) -> str | None:
    text = question.lower()
    if _contains_any(
        text,
        ("average check", "avg check", "average ticket", "средний чек", "միջին չեկ"),
    ):
        return "average_check"
    if _contains_any(
        text,
        ("gross profit", "gross margin", "валовая прибыль", "համախառն շահույթ"),
    ):
        return "gross_profit"
    if _contains_any(text, ("order count", "number of orders", "сколько заказ", "քանի պատվ")):
        return "order_count"
    if _contains_any(text, ("total sales", "total revenue", "общие продажи", "ընդհանուր վաճառ")):
        return "sales_total"
    if _contains_any(
        text,
        ("collection rate", "paid vs invoiced", "собираемость", "հավաքագրման տոկոս"),
    ):
        return "payment_collection"
    if _contains_any(text, ("outstanding balance", "задолж", "չմարված")):
        return "outstanding_balance"
    if _contains_any(text, ("repeat customer", "повторн", "կրկնվող հաճախ")):
        return "repeat_customer_rate"
    return None


def _extract_entity(question: str) -> str | None:
    text = question.lower()
    if _contains_any(text, ("source", "источник", "աղբյուր")):
        return "source"
    if _contains_any(text, ("courier", "курьер", "առաքիչ")):
        return "courier"
    if _contains_any(text, ("address", "location", "адрес", "հասցե")):
        return "location"
    if _contains_any(text, ("customer", "client", "клиент", "հաճախորդ")):
        return "customer"
    if _contains_any(text, ("delivery", "доставка", "առաքում")):
        return "delivery"
    if _contains_any(text, ("payment", "оплат", "վճար")):
        return "payment"
    return None


def _extract_source_filter(question: str) -> str | None:
    source_match = re.search(r"source\s*[:=]\s*([a-zA-Z0-9_ -]+)", question, re.IGNORECASE)
    if source_match is not None:
        source = source_match.group(1).strip().lower().replace(" ", "_")
        return source or None

    text = question.lower()
    for source_name in ("glovo", "wolt", "takeaway", "in_store"):
        if source_name in text:
            return source_name
    if "in store" in text:
        return "in_store"
    return None


def _extract_query_slots(question: str) -> QuerySlots:
    return QuerySlots(
        top_n=_extract_top_n(question),
        group_by=_extract_group_by(question),
        metric=_extract_metric(question),
        entity=_extract_entity(question),
        source=_extract_source_filter(question),
    )


def _detect_report_candidates(question: str) -> list[ReportType]:
    text = question.lower()
    candidates: list[ReportType] = []

    def add(report_id: ReportType) -> None:
        if report_id not in candidates:
            candidates.append(report_id)

    if _contains_any(
        text,
        (
            "location concentration",
            "top location share",
            "address concentration",
            "концентрац",
            "կենտրոնաց",
        ),
    ):
        add(ReportType.LOCATION_CONCENTRATION)
    if _contains_any(
        text,
        (
            "gross profit",
            "gross margin",
            "валовая прибыль",
            "валовая маржа",
            "համախառն շահույթ",
            "մարժա",
        ),
    ):
        add(ReportType.GROSS_PROFIT)
    if _contains_any(
        text,
        (
            "sales by weekday",
            "by weekday",
            "day of week",
            "день недели",
            "дням недели",
            "շաբաթվա օր",
        ),
    ):
        add(ReportType.SALES_BY_WEEKDAY)
    if (
        _contains_any(text, ("daily", "per day", "օրական", "ежеднев"))
        and _contains_any(text, ("order", "orders", "заказ", "պատվեր"))
    ):
        add(ReportType.DAILY_ORDER_TREND)
    if (
        _contains_any(text, ("daily", "per day", "օրական", "ежеднев"))
        and _contains_any(text, ("sales", "revenue", "продаж", "վաճառ"))
    ):
        add(ReportType.DAILY_SALES_TREND)
    if _contains_any(
        text,
        (
            "outstanding balance",
            "receivable",
            "accounts receivable",
            "задолж",
            "долг",
            "չմարված",
            "պարտք",
        ),
    ):
        add(ReportType.OUTSTANDING_BALANCE)
    if _contains_any(
        text,
        (
            "payment collection",
            "collection rate",
            "paid vs invoiced",
            "собираем",
            "оплат",
            "վճարումների հավաք",
            "վճարված",
        ),
    ):
        add(ReportType.PAYMENT_COLLECTION)
    if _contains_any(
        text,
        (
            "delivery fee",
            "delivery cost",
            "shipping fee",
            "стоимость доставки",
            "առաքման գումար",
            "առաքման վճար",
        ),
    ):
        add(ReportType.DELIVERY_FEE_ANALYTICS)
    if _contains_any(
        text,
        (
            "repeat customer",
            "repeat rate",
            "loyal customer",
            "повторн",
            "կրկնվող հաճախ",
        ),
    ):
        add(ReportType.REPEAT_CUSTOMER_RATE)
    if _contains_any(
        text,
        (
            "top customer",
            "best customer",
            "customer ranking",
            "customer by phone",
            "топ клиент",
            "հաճախորդ",
        ),
    ):
        add(ReportType.TOP_CUSTOMERS)
    if _contains_any(
        text,
        (
            "top location",
            "popular location",
            "top address",
            "address ranking",
            "location ranking",
            "топ адрес",
            "популярн",
            "հասցե",
            "լոկացիա",
        ),
    ):
        add(ReportType.TOP_LOCATIONS)
    if _contains_any(
        text,
        (
            "sales by courier",
            "by courier",
            "courier performance",
            "курьер",
            "առաքիչ",
        ),
    ):
        add(ReportType.SALES_BY_COURIER)
    if _contains_any(
        text,
        (
            "sales by source",
            "by source",
            "source mix",
            "channel mix",
            "по источ",
            "աղբյուր",
        ),
    ):
        add(ReportType.SALES_BY_SOURCE)
    if _contains_any(
        text,
        (
            "average check",
            "avg check",
            "average ticket",
            "средний чек",
            "միջին չեկ",
        ),
    ):
        add(ReportType.AVERAGE_CHECK)
    if _contains_any(
        text,
        (
            "order count",
            "number of orders",
            "сколько заказ",
            "քանի պատվ",
        ),
    ):
        add(ReportType.ORDER_COUNT)
    if _contains_any(
        text,
        (
            "total sales",
            "total revenue",
            "общие продажи",
            "ընդհանուր վաճառ",
        ),
    ):
        add(ReportType.SALES_TOTAL)

    if not candidates and _contains_any(text, ("orders", "заказ", "պատվեր")):
        add(ReportType.ORDER_COUNT)
    if not candidates and _contains_any(text, ("sales", "revenue", "продаж", "վաճառ")):
        add(ReportType.SALES_TOTAL)

    return candidates


def _map_slots_to_report(slots: QuerySlots) -> ReportType | None:
    if slots.group_by == "source":
        return ReportType.SALES_BY_SOURCE
    if slots.group_by == "courier":
        return ReportType.SALES_BY_COURIER
    if slots.group_by == "weekday":
        return ReportType.SALES_BY_WEEKDAY
    if slots.group_by == "location":
        return ReportType.TOP_LOCATIONS
    if slots.group_by == "customer":
        return ReportType.TOP_CUSTOMERS

    metric_to_report = {
        "average_check": ReportType.AVERAGE_CHECK,
        "gross_profit": ReportType.GROSS_PROFIT,
        "order_count": ReportType.ORDER_COUNT,
        "sales_total": ReportType.SALES_TOTAL,
        "payment_collection": ReportType.PAYMENT_COLLECTION,
        "outstanding_balance": ReportType.OUTSTANDING_BALANCE,
        "repeat_customer_rate": ReportType.REPEAT_CUSTOMER_RATE,
    }
    if slots.metric in metric_to_report:
        return metric_to_report[slots.metric]

    entity_to_report = {
        "source": ReportType.SALES_BY_SOURCE,
        "courier": ReportType.SALES_BY_COURIER,
        "location": ReportType.TOP_LOCATIONS,
        "customer": ReportType.TOP_CUSTOMERS,
        "delivery": ReportType.DELIVERY_FEE_ANALYTICS,
        "payment": ReportType.PAYMENT_COLLECTION,
    }
    return entity_to_report.get(slots.entity or "")


def _resolve_report_ids(question: str) -> tuple[ReportType | None, list[ReportType], bool]:
    slots = _extract_query_slots(question)
    candidates = _detect_report_candidates(question)
    if not candidates:
        mapped = _map_slots_to_report(slots)
        if mapped is not None:
            candidates = [mapped]

    if not candidates:
        return None, [], False

    primary = candidates[0]
    additional = candidates[1:]
    truncated = False
    if len(additional) > _MAX_MULTI_REPORTS - 1:
        additional = additional[: _MAX_MULTI_REPORTS - 1]
        truncated = True
    return primary, additional, truncated


def _detect_report_id(question: str) -> ReportType | None:
    primary, _, _ = _resolve_report_ids(question)
    return primary


def _has_explicit_or_relative_time_signal(question: str) -> bool:
    return _DATE_RANGE_PATTERN.search(question) is not None or _extract_relative_filters(
        question,
        today=_today(),
    ) is not None


def _contains_text_term(text: str, term: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None


def _is_small_talk(question: str) -> bool:
    text = question.lower()
    if _detect_report_id(text) is not None:
        return False
    if _has_explicit_or_relative_time_signal(text):
        return False

    small_talk_terms = (
        "hi",
        "hello",
        "hey",
        "good morning",
        "good afternoon",
        "good evening",
        "how are you",
        "thanks",
        "thank you",
        "thx",
        "yo",
        "sup",
        "привет",
        "здравствуйте",
        "доброе утро",
        "добрый день",
        "добрый вечер",
        "как дела",
        "спасибо",
        "thanks a lot",
        "barev",
        "բարև",
        "բարեւ",
        "ողջույն",
        "բարի լույս",
        "բարի օր",
        "ինչպես ես",
        "շնորհակալ",
        "շնորհակալություն",
    )
    return any(_contains_text_term(text, term) for term in small_talk_terms)


def _today() -> date:
    return date.today()


def _first_day_of_month(day: date) -> date:
    return day.replace(day=1)


def _shift_month_start(month_start: date, delta_months: int) -> date:
    month_index = (month_start.year * 12 + (month_start.month - 1)) + delta_months
    shifted_year = month_index // 12
    shifted_month = month_index % 12 + 1
    return date(shifted_year, shifted_month, 1)


def _build_filters(date_from: date, date_to: date) -> ReportFilters | None:
    try:
        return ReportFilters(date_from=date_from, date_to=date_to)
    except ValueError:
        return None


def _extract_relative_filters(question: str, *, today: date) -> ReportFilters | None:
    text = question.lower()

    day_patterns = (
        r"\b(?:last|past)\s+(?P<n>\d{1,3})\s+days?\b",
        r"\b(?:последн(?:ие|их)|за)\s+(?P<n>\d{1,3})\s+дн(?:я|ей)\b",
        r"վերջին\s+(?P<n>\d{1,3})\s+օր",
    )
    week_patterns = (
        r"\b(?:last|past)\s+(?P<n>\d{1,3})\s+weeks?\b",
        r"\b(?:последн(?:ие|их)|за)\s+(?P<n>\d{1,3})\s+недел(?:ю|и|ь)\b",
        r"վերջին\s+(?P<n>\d{1,3})\s+շաբաթ",
    )
    month_patterns = (
        r"\b(?:last|past)\s+(?P<n>\d{1,3})\s+months?\b",
        r"\b(?:последн(?:ие|их)|за)\s+(?P<n>\d{1,3})\s+месяц(?:а|ев)?\b",
        r"վերջին\s+(?P<n>\d{1,3})\s+ամիս",
    )
    year_patterns = (
        r"\b(?:last|past)\s+(?P<n>\d{1,3})\s+years?\b",
        r"\b(?:последн(?:ие|их)|за)\s+(?P<n>\d{1,3})\s+год(?:а|ов)?\b",
        r"վերջին\s+(?P<n>\d{1,3})\s+տար",
    )

    for pattern in day_patterns:
        match = re.search(pattern, text)
        if match is None:
            continue
        count = int(match.group("n"))
        if count <= 0:
            return None
        return _build_filters(today - timedelta(days=count - 1), today)

    for pattern in week_patterns:
        match = re.search(pattern, text)
        if match is None:
            continue
        count = int(match.group("n"))
        if count <= 0:
            return None
        return _build_filters(today - timedelta(days=7 * count - 1), today)

    for pattern in month_patterns:
        match = re.search(pattern, text)
        if match is None:
            continue
        count = int(match.group("n"))
        if count <= 0:
            return None
        current_month_start = _first_day_of_month(today)
        period_start = _shift_month_start(current_month_start, -(count - 1))
        return _build_filters(period_start, today)

    for pattern in year_patterns:
        match = re.search(pattern, text)
        if match is None:
            continue
        count = int(match.group("n"))
        if count <= 0:
            return None
        period_start = date(today.year - (count - 1), 1, 1)
        return _build_filters(period_start, today)

    if _contains_any(text, ("today", "сегодня", "այսօր")):
        return _build_filters(today, today)
    if _contains_any(text, ("yesterday", "вчера", "երեկ")):
        day = today - timedelta(days=1)
        return _build_filters(day, day)

    if _contains_any(
        text,
        (
            "this week",
            "current week",
            "this_week",
            "этой неделе",
            "эта неделя",
            "текущая неделя",
            "текущей неделе",
            "այս շաբաթ",
        ),
    ):
        this_week_start = today - timedelta(days=today.weekday())
        return _build_filters(this_week_start, today)
    if _contains_any(
        text,
        (
            "last week",
            "previous week",
            "last_week",
            "прошлая неделя",
            "прошлую неделю",
            "прошлой неделе",
            "предыдущая неделя",
            "предыдущую неделю",
            "предыдущей неделе",
            "նախորդ շաբաթ",
        ),
    ):
        this_week_start = today - timedelta(days=today.weekday())
        last_week_end = this_week_start - timedelta(days=1)
        last_week_start = last_week_end - timedelta(days=6)
        return _build_filters(last_week_start, last_week_end)

    if _contains_any(
        text,
        (
            "this month",
            "current month",
            "этот месяц",
            "текущий месяц",
            "этом месяце",
            "այս ամիս",
        ),
    ):
        return _build_filters(_first_day_of_month(today), today)
    if _contains_any(
        text,
        (
            "last month",
            "previous month",
            "прошлый месяц",
            "прошлом месяце",
            "предыдущий месяц",
            "предыдущем месяце",
            "նախորդ ամիս",
        ),
    ):
        this_month_start = _first_day_of_month(today)
        last_month_end = this_month_start - timedelta(days=1)
        last_month_start = _first_day_of_month(last_month_end)
        return _build_filters(last_month_start, last_month_end)

    if _contains_any(
        text,
        ("this year", "current year", "этот год", "этом году", "այս տարի"),
    ):
        return _build_filters(date(today.year, 1, 1), today)
    if _contains_any(
        text,
        (
            "last year",
            "previous year",
            "прошлый год",
            "прошлом году",
            "предыдущий год",
            "предыдущем году",
            "նախորդ տարի",
        ),
    ):
        return _build_filters(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31))

    return None


def _extract_filters(question: str) -> ReportFilters | None:
    match = _DATE_RANGE_PATTERN.search(question)
    if match is not None:
        try:
            date_from = date.fromisoformat(match.group(1))
            date_to = date.fromisoformat(match.group(2))
            return ReportFilters(date_from=date_from, date_to=date_to)
        except ValueError:
            return None

    return _extract_relative_filters(question, today=_today())


def _generate_interpretation_payload(question: str) -> dict[str, Any]:
    if _is_small_talk(question):
        return {
            "intent": IntentType.SMALL_TALK,
            "report_id": None,
            "filters": None,
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.98,
            "reasoning_notes": "Deterministic small-talk classification.",
        }

    selected_report_id = _detect_report_id(question)
    slots = _extract_query_slots(question)
    if selected_report_id is None:
        return {
            "intent": IntentType.UNSUPPORTED_REQUEST,
            "report_id": None,
            "filters": None,
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.3,
            "reasoning_notes": (
                "No supported report matched deterministic slots: "
                f"group_by={slots.group_by}, metric={slots.metric}, entity={slots.entity}."
            ),
        }

    filters = _extract_filters(question)
    if filters is None:
        return {
            "intent": IntentType.NEEDS_CLARIFICATION,
            "report_id": selected_report_id,
            "filters": None,
            "needs_clarification": True,
            "clarification_question": (
                "Please provide a date range (YYYY-MM-DD to YYYY-MM-DD) "
                "or a relative period like today / last week / last 3 months."
            ),
            "confidence": 0.7,
            "reasoning_notes": "Report candidate detected but required date range is missing.",
        }

    if selected_report_id is ReportType.SALES_BY_SOURCE and slots.source:
        filters = filters.model_copy(update={"source": slots.source})

    intent = (
        IntentType.BREAKDOWN_KPI
        if selected_report_id in _BREAKDOWN_REPORT_IDS
        else IntentType.GET_KPI
    )
    return {
        "intent": intent,
        "report_id": selected_report_id,
        "filters": filters,
        "needs_clarification": False,
        "clarification_question": None,
        "confidence": 0.9,
        "reasoning_notes": (
            "Report and filters identified with deterministic slot extraction: "
            f"group_by={slots.group_by}, metric={slots.metric}, entity={slots.entity}, "
            f"top_n={slots.top_n}, source={slots.source}."
        ),
    }


def _should_query_llm(deterministic_payload: dict[str, Any]) -> bool:
    return deterministic_payload.get("intent") == IntentType.UNSUPPORTED_REQUEST


def _interpret_request_with_llm(
    question: str,
    llm_client: Any,
) -> dict[str, Any]:
    messages = build_interpret_request_messages(question)
    output_text = llm_client.generate_text(messages=messages)
    interpretation = parse_interpretation_output_json(output_text)
    return interpretation.model_dump(mode="python")


def _resolve_scope_node(state: AgentState) -> dict[str, Any]:
    if state.scope_request is None:
        return {
            "status": RunStatus.DENIED,
            "final_answer": _localized_message(state, "access_denied_missing_scope"),
            "warnings": [*state.warnings, "missing_scope_request"],
        }

    scope_response = resolve_scope_tool(state.scope_request)
    tool_responses = state.tool_responses.model_copy(deep=True)
    tool_responses.resolve_scope = scope_response
    return {"user_scope": scope_response, "tool_responses": tool_responses}


def _openai_interpret_node(state: AgentState) -> dict[str, Any]:
    warnings = [*state.warnings]
    slots = _extract_query_slots(state.user_question)
    _, additional_report_ids, multi_intent_truncated = _resolve_report_ids(state.user_question)
    deterministic_interpretation = _generate_interpretation_payload(state.user_question)
    try:
        raw_interpretation = deterministic_interpretation
        if _should_query_llm(deterministic_interpretation):
            try:
                llm_client = get_llm_client()
            except ValueError:
                raw_interpretation = deterministic_interpretation
            else:
                try:
                    raw_interpretation = _interpret_request_with_llm(
                        state.user_question,
                        llm_client,
                    )
                except LLMClientError as exc:
                    if exc.category is not LLMErrorCategory.RATE_LIMIT:
                        raise
                    raw_interpretation = deterministic_interpretation
                    warnings.append(_INTERPRET_RATE_LIMIT_FALLBACK_WARNING)

        interpretation = validate_interpretation_output(raw_interpretation)
    except InterpretationContractError:
        return {
            "intent": IntentType.NEEDS_CLARIFICATION,
            "selected_report_id": None,
            "filters": None,
            "needs_clarification": True,
            "clarification_question": CLARIFICATION_FALLBACK_QUESTION,
            "warnings": [*warnings, "interpretation_contract_invalid"],
        }

    if multi_intent_truncated:
        warnings.append("multi_intent_truncated")

    if (
        interpretation.report_id is not ReportType.SALES_BY_SOURCE
        and interpretation.filters is not None
        and interpretation.filters.source is not None
    ):
        interpretation_filters = interpretation.filters.model_copy(update={"source": None})
    else:
        interpretation_filters = interpretation.filters

    additional_report_ids = [
        report_id
        for report_id in additional_report_ids
        if report_id is not interpretation.report_id
    ]
    if interpretation.intent in {
        IntentType.NEEDS_CLARIFICATION,
        IntentType.UNSUPPORTED_REQUEST,
        IntentType.SMALL_TALK,
    }:
        additional_report_ids = []

    return {
        "intent": interpretation.intent,
        "selected_report_id": interpretation.report_id,
        "filters": interpretation_filters,
        "needs_clarification": interpretation.needs_clarification,
        "clarification_question": interpretation.clarification_question,
        "additional_report_ids": additional_report_ids,
        "additional_run_reports": [],
        "requested_top_n": slots.top_n,
        "slot_group_by": slots.group_by,
        "slot_metric": slots.metric,
        "slot_entity": slots.entity,
        "warnings": warnings,
    }


def _authorize_report_node(state: AgentState) -> dict[str, Any]:
    if state.user_scope is None or state.user_scope.status is AccessStatus.DENIED:
        return {"status": RunStatus.DENIED}

    if state.intent is IntentType.SMALL_TALK:
        return {"status": RunStatus.COMPLETED}

    if state.needs_clarification or state.intent is IntentType.NEEDS_CLARIFICATION:
        question = _localized_clarification_question(state)
        return {
            "status": RunStatus.CLARIFY,
            "needs_clarification": True,
            "clarification_question": question,
        }

    if state.intent is IntentType.UNSUPPORTED_REQUEST or state.selected_report_id is None:
        return {"status": RunStatus.REJECTED}

    if state.filters is None:
        question = _localized_clarification_question(state)
        return {
            "status": RunStatus.CLARIFY,
            "needs_clarification": True,
            "clarification_question": question,
        }

    requested_reports = [state.selected_report_id, *state.additional_report_ids]
    disallowed_reports = [
        report_id
        for report_id in requested_reports
        if report_id not in state.user_scope.allowed_report_ids
    ]
    if disallowed_reports:
        return {
            "status": RunStatus.DENIED,
            "warnings": [*state.warnings, _AUTHORIZATION_BLOCKED_WARNING],
        }

    return {"status": RunStatus.RUNNING}


def _select_authorization_route(state: AgentState) -> str:
    if state.status is RunStatus.COMPLETED and state.intent is IntentType.SMALL_TALK:
        return "small_talk"
    if state.status is RunStatus.DENIED:
        return "deny"
    if state.status is RunStatus.CLARIFY:
        return "clarify"
    if state.status is RunStatus.REJECTED:
        return "reject"
    if state.status is RunStatus.FAILED:
        return "fail"
    if state.status is RunStatus.RUNNING:
        return "run_report"
    return "fail"


def _run_report_node(state: AgentState) -> dict[str, Any]:
    if state.scope_request is None or state.selected_report_id is None or state.filters is None:
        return {
            "status": RunStatus.FAILED,
            "final_answer": _localized_message(state, "run_failed_missing_context"),
            "warnings": [*state.warnings, "run_report_missing_context"],
        }

    def _filters_for_report(report_id: ReportType, filters: ReportFilters) -> ReportFilters:
        if report_id is ReportType.SALES_BY_SOURCE:
            return filters
        if filters.source is None:
            return filters
        return filters.model_copy(update={"source": None})

    run_request = RunReportRequest(
        user_id=state.scope_request.user_id,
        profile_id=state.scope_request.profile_id,
        profile_nick=state.scope_request.profile_nick,
        request=ReportRequest(
            report_id=state.selected_report_id,
            filters=_filters_for_report(state.selected_report_id, state.filters),
        ),
    )
    try:
        run_response = run_report_tool(run_request)
    except Exception:
        return {
            "status": RunStatus.FAILED,
            "final_answer": _localized_message(state, "run_failed_execution_error"),
            "warnings": [*state.warnings, "run_report_execution_failed"],
        }

    additional_run_reports: list[Any] = []
    for report_id in state.additional_report_ids:
        additional_request = RunReportRequest(
            user_id=state.scope_request.user_id,
            profile_id=state.scope_request.profile_id,
            profile_nick=state.scope_request.profile_nick,
            request=ReportRequest(
                report_id=report_id,
                filters=_filters_for_report(report_id, state.filters),
            ),
        )
        try:
            additional_response = run_report_tool(additional_request)
        except Exception:
            return {
                "status": RunStatus.FAILED,
                "final_answer": _localized_message(state, "run_failed_execution_error"),
                "warnings": [*state.warnings, "run_report_execution_failed"],
            }
        additional_run_reports.append(additional_response)

    tool_responses = state.tool_responses.model_copy(deep=True)
    tool_responses.run_report = run_response
    warnings = [*state.warnings, *run_response.warnings]
    for extra_response in additional_run_reports:
        warnings.extend(extra_response.warnings)
    return {
        "tool_responses": tool_responses,
        "additional_run_reports": additional_run_reports,
        "warnings": warnings,
    }


def _select_next_after_run_report(state: AgentState) -> str:
    if state.status is RunStatus.FAILED:
        return "fail"
    return "calc_metrics"


def _calc_metrics_node(state: AgentState) -> dict[str, Any]:
    run_response = state.tool_responses.run_report
    if run_response is None:
        return {
            "status": RunStatus.FAILED,
            "final_answer": _localized_message(state, "calc_missing_report_output"),
            "warnings": [*state.warnings, "calc_missing_report_output"],
        }

    try:
        base_metrics = map_report_response_to_base_metrics(run_response)
    except ValueError:
        return {
            "status": RunStatus.FAILED,
            "final_answer": _localized_message(state, "calc_mapping_failed"),
            "warnings": [*state.warnings, "calc_mapping_failed"],
        }

    report_id = state.selected_report_id or run_response.result.report_id
    calculation_specs = select_calculation_specs(report_id, state.intent, base_metrics)

    if not calculation_specs:
        return {
            "base_metrics": base_metrics,
            "derived_metrics": [],
            "calc_warnings": [],
            "warnings": [*state.warnings, "calc_no_formulas_selected"],
        }

    request = ComputeMetricsRequest(
        base_metrics=base_metrics,
        calculations=calculation_specs,
    )
    response = compute_metrics_tool(request)
    calc_warning_strings = [f"calc:{warning.value}" for warning in response.warnings]
    return {
        "base_metrics": base_metrics,
        "derived_metrics": response.derived_metrics,
        "calc_warnings": response.warnings,
        "warnings": [*state.warnings, *calc_warning_strings],
    }


def _select_next_after_calc_metrics(state: AgentState) -> str:
    if state.status is RunStatus.FAILED:
        return "fail"
    return "reason_over_results"


def _reason_over_results_node(state: AgentState) -> dict[str, Any]:
    run_response = state.tool_responses.run_report
    if run_response is None:
        return {
            "status": RunStatus.FAILED,
            "final_answer": _localized_message(state, "reason_missing_tool_output"),
            "warnings": [*state.warnings, "reason_missing_tool_output"],
        }
    return {}


def _select_next_after_reasoning(state: AgentState) -> str:
    if state.status is RunStatus.FAILED:
        return "fail"
    return "compose_output"


def _clarify_node(state: AgentState) -> dict[str, Any]:
    question = _localized_clarification_question(state)
    return {
        "status": RunStatus.CLARIFY,
        "final_answer": question,
        "needs_clarification": True,
        "clarification_question": question,
    }


def _small_talk_node(state: AgentState) -> dict[str, Any]:
    return {
        "status": RunStatus.COMPLETED,
        "final_answer": _localized_message(state, "small_talk_response"),
    }


def _reject_node(state: AgentState) -> dict[str, Any]:
    return {
        "status": RunStatus.REJECTED,
        "final_answer": _localized_message(state, "unsupported_request"),
    }


def _deny_node(state: AgentState) -> dict[str, Any]:
    return {
        "status": RunStatus.DENIED,
        "final_answer": _localized_message(state, "access_denied_request"),
    }


def _fail_node(state: AgentState) -> dict[str, Any]:
    if state.final_answer:
        return {"status": RunStatus.FAILED}
    return {
        "status": RunStatus.FAILED,
        "final_answer": _localized_message(state, "run_failed_internal"),
        "warnings": [*state.warnings, "runtime_failed"],
    }


def _metrics_for_display(
    report_id: ReportType,
    metrics: list[Any],
    requested_top_n: int | None,
) -> list[Any]:
    if requested_top_n is None:
        return metrics
    if report_id not in _TOP_N_DISPLAY_REPORT_IDS:
        return metrics
    return metrics[:requested_top_n] or metrics


def _compose_single_report_summary(
    state: AgentState,
    *,
    report_id: ReportType,
    filters: ReportFilters,
    metrics: list[Any],
    include_derived: bool,
) -> str:
    display_metrics = _metrics_for_display(report_id, metrics, state.requested_top_n)
    metrics_text = ", ".join(
        f"{_localized_metric_label(state, metric.label)}={metric.value:.2f}"
        for metric in display_metrics
    )
    final_answer = _localized_message(
        state,
        "report_summary",
        report=_localized_report_name(state, report_id),
        date_from=filters.date_from,
        date_to=filters.date_to,
        metrics=metrics_text,
    )

    if not include_derived:
        return final_answer

    not_available = _localized_message(state, "not_available")
    derived_text = ", ".join(
        (
            f"{_localized_metric_label(state, metric.key)}={metric.value:.2f}"
            if metric.value is not None
            else f"{_localized_metric_label(state, metric.key)}={not_available}"
        )
        for metric in state.derived_metrics
    )
    if not derived_text:
        return final_answer
    return f"{final_answer}{_localized_message(state, 'derived_prefix', derived=derived_text)}"


def _compose_output_node(state: AgentState) -> dict[str, Any]:
    run_response = state.tool_responses.run_report
    if run_response is None:
        return {
            "status": RunStatus.FAILED,
            "final_answer": _localized_message(state, "compose_missing_tool_output"),
            "warnings": [*state.warnings, "compose_missing_tool_output"],
        }

    primary_summary = _compose_single_report_summary(
        state,
        report_id=run_response.result.report_id,
        filters=run_response.result.filters,
        metrics=run_response.result.metrics,
        include_derived=True,
    )
    if not state.additional_run_reports:
        final_answer = primary_summary
    else:
        blocks = [primary_summary]
        for extra_response in state.additional_run_reports:
            blocks.append(
                _compose_single_report_summary(
                    state,
                    report_id=extra_response.result.report_id,
                    filters=extra_response.result.filters,
                    metrics=extra_response.result.metrics,
                    include_derived=False,
                )
            )
        numbered_blocks = "\n".join(
            f"{index}. {block}"
            for index, block in enumerate(blocks, start=1)
        )
        final_answer = f"{_localized_message(state, 'multi_report_header')}\n{numbered_blocks}"

    return {
        "status": RunStatus.COMPLETED,
        "final_answer": final_answer,
    }


def _select_next_after_compose(state: AgentState) -> str:
    if state.status is RunStatus.FAILED:
        return "fail"
    return "persist_run"


def build_agent_graph(
    *,
    persistence_service: RuntimePersistenceService | None = None,
) -> Any:
    """Build and compile the minimal Task 9 LangGraph workflow."""
    graph = StateGraph(AgentState)

    def _persist_run_node(state: AgentState) -> dict[str, Any]:
        if persistence_service is None:
            return {}

        finish_persistence_result = persistence_service.finish_run(
            thread_id=state.internal_thread_id,
            internal_run_id=state.internal_run_id,
            status=state.status,
            question=state.user_question,
            answer=state.final_answer,
            error_message=(
                state.final_answer
                if state.status is RunStatus.FAILED
                else None
            ),
        )
        return {
            "warnings": [*state.warnings, *finish_persistence_result.warnings],
            "run_persisted": True,
        }

    graph.add_node("resolve_scope", _resolve_scope_node)
    graph.add_node("openai_interpret", _openai_interpret_node)
    graph.add_node("authorize_report", _authorize_report_node)
    graph.add_node("run_report", _run_report_node)
    graph.add_node("calc_metrics", _calc_metrics_node)
    graph.add_node("reason_over_results", _reason_over_results_node)
    graph.add_node("small_talk", _small_talk_node)
    graph.add_node("clarify", _clarify_node)
    graph.add_node("reject", _reject_node)
    graph.add_node("deny", _deny_node)
    graph.add_node("fail", _fail_node)
    graph.add_node("compose_output", _compose_output_node)
    graph.add_node("persist_run", _persist_run_node)

    graph.set_entry_point("resolve_scope")
    graph.add_edge("resolve_scope", "openai_interpret")
    graph.add_edge("openai_interpret", "authorize_report")
    graph.add_conditional_edges(
        "authorize_report",
        _select_authorization_route,
        {
            "run_report": "run_report",
            "small_talk": "small_talk",
            "clarify": "clarify",
            "reject": "reject",
            "deny": "deny",
            "fail": "fail",
        },
    )
    graph.add_conditional_edges(
        "run_report",
        _select_next_after_run_report,
        {
            "calc_metrics": "calc_metrics",
            "fail": "fail",
        },
    )
    graph.add_conditional_edges(
        "calc_metrics",
        _select_next_after_calc_metrics,
        {
            "reason_over_results": "reason_over_results",
            "fail": "fail",
        },
    )
    graph.add_conditional_edges(
        "reason_over_results",
        _select_next_after_reasoning,
        {
            "compose_output": "compose_output",
            "fail": "fail",
        },
    )
    graph.add_conditional_edges(
        "compose_output",
        _select_next_after_compose,
        {
            "persist_run": "persist_run",
            "fail": "fail",
        },
    )
    graph.add_edge("clarify", "persist_run")
    graph.add_edge("small_talk", "persist_run")
    graph.add_edge("reject", "persist_run")
    graph.add_edge("deny", "persist_run")
    graph.add_edge("fail", "persist_run")
    graph.add_edge("persist_run", END)

    return graph.compile()
