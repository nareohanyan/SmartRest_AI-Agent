"""Minimal LangGraph workflow for Task 9."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph

from app.agent.calc_policy import select_calculation_specs
from app.agent.calc_tools import compute_metrics_tool
from app.agent.llm import (
    CLARIFICATION_FALLBACK_QUESTION,
    FilterMatchContractError,
    InterpretationContractError,
    LLMClientError,
    build_filter_match_messages,
    build_interpret_request_messages,
    build_small_talk_messages,
    get_llm_client,
    parse_filter_match_output_json,
    parse_interpretation_output_json,
    validate_interpretation_output,
)
from app.agent.metrics_mapper import map_report_response_to_base_metrics
from app.agent.report_tools import resolve_filter_value_tool, resolve_scope_tool, run_report_tool
from app.core.config import get_settings
from app.persistence.runtime_persistence import RuntimePersistenceService
from app.reports import get_report_definition
from app.reports.excel_backend import get_excel_data_date_range
from app.reports.filter_resolution import normalize_lookup_text
from app.reports.mock_backend import get_mock_data_date_range
from app.schemas.agent import AgentState, IntentType, LLMErrorCategory, RunStatus
from app.schemas.calculations import ComputeMetricsRequest
from app.schemas.reports import ReportFilterKey, ReportFilters, ReportRequest, ReportType
from app.schemas.tools import (
    AccessStatus,
    ResolveFilterValueRequest,
    ResolveFilterValueStatus,
    RunReportRequest,
)

_DATE_RANGE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})")
_AUTHORIZATION_BLOCKED_WARNING = "authorization_blocked_report_not_allowed"
_INTERPRET_RATE_LIMIT_FALLBACK_WARNING = "interpretation_rate_limit_fallback"
_INTERPRET_LLM_FALLBACK_WARNING = "interpretation_llm_fallback"
_FILTER_RESOLUTION_LLM_WARNING = "filter_resolution_llm_used"
_MAX_MULTI_REPORTS = 3
_FILTER_MATCH_CONFIDENCE_THRESHOLD = 0.75
_FILTER_FIELD_BY_KEY = {
    ReportFilterKey.SOURCE: "source",
    ReportFilterKey.COURIER: "courier",
    ReportFilterKey.LOCATION: "location",
    ReportFilterKey.PHONE_NUMBER: "phone_number",
}
_DEFAULT_CLARIFICATION_QUESTIONS = {
    CLARIFICATION_FALLBACK_QUESTION,
    "Please clarify which report or filter you want me to use.",
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
        "clarify_need_date_range": "Please clarify which report or filter you want me to use.",
        "unsupported_request": (
            "Unsupported request. Supported scopes include sales, sources, couriers, "
            "customers, locations, delivery fees, payments, balances, weekday and daily trends, "
            "and gross-profit analytics."
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
        "clarify_need_date_range": "Խնդրում եմ հստակեցրեք՝ որ "
                                   "հաշվետվությունը կամ ֆիլտրն եք ուզում օգտագործել։",
        "unsupported_request": (
            "Չաջակցվող հարցում։ Աջակցվում են վաճառք, աղբյուրներ, առաքիչներ, "
            "հաճախորդներ, հասցեներ, առաքման վճար, վճարումներ, մնացորդ, "
            "օրական և շաբաթվա տրենդեր, ինչպես նաև համախառն շահույթի վերլուծություն։"
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
        "clarify_need_date_range": "Пожалуйста, уточните, "
                                   "какой отчет или фильтр нужно использовать.",
        "unsupported_request": (
            "Неподдерживаемый запрос. Поддерживаются аналитика продаж, источников, "
            "курьеров, клиентов, локаций, доставки, оплат, задолженности, "
            "дневных/недельных трендов и валовой прибыли."
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
        "sales_total": "total sales",
        "order_count": "order count",
        "average_check": "average check",
        "sales_by_source": "sales by source",
        "sales_by_courier": "sales by courier",
        "top_locations": "top locations",
        "top_customers": "top customers",
        "repeat_customer_rate": "repeat customer rate",
        "delivery_fee_analytics": "delivery fee analytics",
        "payment_collection": "payment collection",
        "outstanding_balance": "outstanding balance",
        "daily_sales_trend": "daily sales trend",
        "daily_order_trend": "daily order trend",
        "sales_by_weekday": "sales by weekday",
        "gross_profit": "gross profit",
        "location_concentration": "location concentration",
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
        "sales_total": "total sales",
        "order_count": "order count",
        "average_check": "average check",
        "sales_total_per_day": "average daily sales",
        "order_count_per_day": "average daily order count",
        "delivery_fee_total": "total delivery fee",
        "delivery_fee_average": "average delivery fee",
        "collection_rate_percent": "collection rate",
        "invoiced_total": "invoiced total",
        "paid_total": "paid total",
        "outstanding_balance": "outstanding balance",
        "gross_profit": "gross profit",
        "gross_margin_percent": "gross margin",
        "repeat_customer_rate_percent": "repeat customer rate",
        "repeat_customer_count": "repeat customer count",
        "top_10_location_share_percent": "top 10 location share",
        "top_1_location_share_percent": "top location share",
        "distinct_locations_count": "distinct locations",
    },
    "hy": {
        "sales_total": "ընդհանուր վաճառք",
        "order_count": "պատվերների քանակ",
        "average_check": "միջին չեկ",
        "sales_total_per_day": "օրական միջին վաճառք",
        "order_count_per_day": "օրական միջին պատվերների քանակ",
        "delivery_fee_total": "առաքման վճար (ընդհանուր)",
        "delivery_fee_average": "առաքման միջին վճար",
        "collection_rate_percent": "հավաքագրման տոկոս",
        "invoiced_total": "դուրս գրված գումար",
        "paid_total": "վճարված գումար",
        "outstanding_balance": "չմարված մնացորդ",
        "gross_profit": "համախառն շահույթ",
        "gross_margin_percent": "համախառն մարժա",
        "repeat_customer_rate_percent": "կրկնվող հաճախորդների տոկոս",
        "repeat_customer_count": "կրկնվող հաճախորդների քանակ",
        "top_10_location_share_percent": "թոփ 10 հասցեների մասնաբաժին",
        "top_1_location_share_percent": "ամենաակտիվ հասցեի մասնաբաժին",
        "distinct_locations_count": "եզակի հասցեների քանակ",
    },
    "ru": {
        "sales_total": "общие продажи",
        "order_count": "количество заказов",
        "average_check": "средний чек",
        "sales_total_per_day": "продажи в день",
        "order_count_per_day": "заказы в день",
        "delivery_fee_total": "стоимость доставки (итого)",
        "delivery_fee_average": "средняя стоимость доставки",
        "collection_rate_percent": "процент собираемости",
        "invoiced_total": "сумма выставлений",
        "paid_total": "оплаченная сумма",
        "outstanding_balance": "задолженность",
        "gross_profit": "валовая прибыль",
        "gross_margin_percent": "валовая маржа",
        "repeat_customer_rate_percent": "доля повторных клиентов",
        "repeat_customer_count": "число повторных клиентов",
        "top_10_location_share_percent": "доля топ 10 локаций",
        "top_1_location_share_percent": "доля топ локации",
        "distinct_locations_count": "число уникальных локаций",
    },
}

_LOCALIZED_FILTER_LABELS: dict[str, dict[ReportFilterKey, str]] = {
    "en": {
        ReportFilterKey.SOURCE: "source",
        ReportFilterKey.COURIER: "courier",
        ReportFilterKey.LOCATION: "location",
        ReportFilterKey.PHONE_NUMBER: "phone number",
    },
    "hy": {
        ReportFilterKey.SOURCE: "աղբյուրը",
        ReportFilterKey.COURIER: "առաքիչը",
        ReportFilterKey.LOCATION: "հասցեն",
        ReportFilterKey.PHONE_NUMBER: "հեռախոսահամարը",
    },
    "ru": {
        ReportFilterKey.SOURCE: "источник",
        ReportFilterKey.COURIER: "курьера",
        ReportFilterKey.LOCATION: "локацию",
        ReportFilterKey.PHONE_NUMBER: "номер телефона",
    },
}

_LOCALIZED_WEEKDAY_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "monday": "Monday",
        "tuesday": "Tuesday",
        "wednesday": "Wednesday",
        "thursday": "Thursday",
        "friday": "Friday",
        "saturday": "Saturday",
        "sunday": "Sunday",
    },
    "hy": {
        "monday": "Երկուշաբթի",
        "tuesday": "Երեքշաբթի",
        "wednesday": "Չորեքշաբթի",
        "thursday": "Հինգշաբթի",
        "friday": "Ուրբաթ",
        "saturday": "Շաբաթ",
        "sunday": "Կիրակի",
    },
    "ru": {
        "monday": "понедельник",
        "tuesday": "вторник",
        "wednesday": "среда",
        "thursday": "четверг",
        "friday": "пятница",
        "saturday": "суббота",
        "sunday": "воскресенье",
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
    return _LOCALIZED_REPORT_NAMES[language].get(
        report_id.value,
        _humanize_identifier(report_id.value),
    )


def _localized_filter_label(state: AgentState, filter_key: ReportFilterKey) -> str:
    language = _response_language(state.user_question)
    return _LOCALIZED_FILTER_LABELS[language][filter_key]


def _optional_filter_keys(report_id: ReportType | None) -> set[ReportFilterKey]:
    if report_id is None:
        return set()
    definition = get_report_definition(report_id)
    return set(definition.optional_filters)


def _non_null_filter_count(filters: ReportFilters | None) -> int:
    if filters is None:
        return 0
    return sum(
        1
        for field_name in _FILTER_FIELD_BY_KEY.values()
        if getattr(filters, field_name) is not None
    )


def _strip_incompatible_filters(
    report_id: ReportType | None,
    filters: ReportFilters | None,
) -> ReportFilters | None:
    if filters is None or report_id is None:
        return filters

    allowed = _optional_filter_keys(report_id)
    filter_updates = {
        field_name: None
        for filter_key, field_name in _FILTER_FIELD_BY_KEY.items()
        if filter_key not in allowed and getattr(filters, field_name) is not None
    }
    if not filter_updates:
        return filters
    return filters.model_copy(update=filter_updates)


def _humanize_identifier(value: str) -> str:
    return " ".join(value.strip().replace("_", " ").split())


def _display_dimension_value(state: AgentState, value: str) -> str:
    normalized_value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized_value):
        return normalized_value

    language = _response_language(state.user_question)
    weekday_key = normalized_value.lower().replace(" ", "_")
    if weekday_key in _LOCALIZED_WEEKDAY_LABELS[language]:
        return _LOCALIZED_WEEKDAY_LABELS[language][weekday_key]

    humanized = _humanize_identifier(normalized_value)
    if humanized.lower() == humanized and any(ch.isalpha() for ch in humanized):
        return humanized.title()
    return humanized


def _join_human_list(state: AgentState, items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]

    language = _response_language(state.user_question)
    conjunction = {"en": "and", "hy": "և", "ru": "и"}[language]
    if len(items) == 2:
        return f"{items[0]} {conjunction} {items[1]}"
    return f"{', '.join(items[:-1])}, {conjunction} {items[-1]}"


def _capitalize_first(text: str) -> str:
    stripped = text.lstrip()
    if not stripped:
        return text
    prefix_length = len(text) - len(stripped)
    return f"{text[:prefix_length]}{stripped[0].upper()}{stripped[1:]}"


def _compact_join(items: list[str]) -> str:
    return ", ".join(item for item in items if item)


def _is_percentage_metric(metric_key: str) -> bool:
    return "percent" in metric_key


def _format_numeric_value(value: Any, *, as_percentage: bool = False) -> str:
    numeric = Decimal(str(value))
    if numeric == numeric.to_integral():
        formatted = f"{numeric:,.0f}"
    else:
        formatted = f"{numeric:,.2f}"
    if as_percentage:
        return f"{formatted}%"
    return formatted


def _localized_metric_label(state: AgentState, label: str) -> str:
    language = _response_language(state.user_question)
    localized = _LOCALIZED_METRIC_LABELS[language].get(label)
    if localized is not None:
        return localized

    if label.startswith("share_percent_"):
        entity = _display_dimension_value(state, label.removeprefix("share_percent_"))
        if language == "hy":
            return f"{entity} մասնաբաժին"
        if language == "ru":
            return f"доля {entity}"
        return f"{entity} share"

    if label.endswith("_per_day"):
        base = _localized_metric_label(state, label.removesuffix("_per_day"))
        if language == "hy":
            return f"{base} օրական"
        if language == "ru":
            return f"{base} в день"
        return f"{base} per day"

    if label.endswith("_delta"):
        base = _localized_metric_label(state, label.removesuffix("_delta"))
        if language == "hy":
            return f"{base} փոփոխություն"
        if language == "ru":
            return f"изменение {base}"
        return f"change in {base}"

    if label.endswith("_percent_change"):
        base = _localized_metric_label(state, label.removesuffix("_percent_change"))
        if language == "hy":
            return f"{base} տոկոսային փոփոխություն"
        if language == "ru":
            return f"процентное изменение {base}"
        return f"percentage change in {base}"

    return _humanize_identifier(label)


def _active_dimension_filters(
    state: AgentState,
    filters: ReportFilters | None,
) -> list[tuple[ReportFilterKey, str]]:
    if filters is None:
        return []

    active: list[tuple[ReportFilterKey, str]] = []
    for filter_key, field_name in _FILTER_FIELD_BY_KEY.items():
        raw_value = getattr(filters, field_name)
        if raw_value is None:
            continue
        active.append((filter_key, _display_dimension_value(state, str(raw_value))))
    return active


def _filter_context_phrase(state: AgentState, filters: ReportFilters | None) -> str | None:
    active_filters = _active_dimension_filters(state, filters)
    if not active_filters:
        return None

    language = _response_language(state.user_question)
    if len(active_filters) > 1:
        if language == "hy":
            return "այդ հատվածում"
        if language == "ru":
            return "в этом срезе"
        return "in that segment"

    filter_key, display_value = active_filters[0]
    if language == "hy":
        if filter_key is ReportFilterKey.SOURCE:
            return f"{display_value} աղբյուրով"
        if filter_key is ReportFilterKey.COURIER:
            return f"{display_value}-ի դեպքում"
        if filter_key is ReportFilterKey.LOCATION:
            return f"{display_value} հասցեում"
        return f"{display_value} համարով"

    if language == "ru":
        if filter_key is ReportFilterKey.SOURCE:
            return f"по источнику {display_value}"
        if filter_key is ReportFilterKey.COURIER:
            return f"по курьеру {display_value}"
        if filter_key is ReportFilterKey.LOCATION:
            return f"по адресу {display_value}"
        return f"по номеру {display_value}"

    if filter_key is ReportFilterKey.SOURCE:
        return f"for {display_value}"
    if filter_key is ReportFilterKey.COURIER:
        return f"for {display_value}"
    if filter_key is ReportFilterKey.LOCATION:
        return f"at {display_value}"
    return f"for phone number {display_value}"


def _build_filter_clarification_question(
    state: AgentState,
    *,
    filter_key: ReportFilterKey,
    raw_value: str,
    candidates: list[str],
) -> str:
    label = _localized_filter_label(state, filter_key)
    language = _response_language(state.user_question)
    if candidates:
        joined_candidates = ", ".join(candidates)
        if language == "hy":
            return (
                f'Չկարողացա հստակ համադրել {label} "{raw_value}" արժեքը։ '
                f'Նկատի ունե՞ք սրանցից մեկը՝ {joined_candidates}։'
            )
        if language == "ru":
            return (
                f'Не удалось уверенно сопоставить {label} "{raw_value}". '
                f'Вы имели в виду одно из следующих значений: {joined_candidates}?'
            )
        return (
            f'I could not confidently match the {label} "{raw_value}". '
            f'Did you mean one of these values: {joined_candidates}?'
        )

    if language == "hy":
        return (
            f'Չգտա ճշգրիտ {label} "{raw_value}" արժեք։ '
            "Նշեք այն ճիշտ ձևով, ինչպես կա տվյալներում։"
        )
    if language == "ru":
        return (
            f'Не удалось найти точное значение {label} "{raw_value}". '
            "Укажите его в точном виде, как оно записано в данных."
        )
    return (
        f'I could not find an exact {label} value for "{raw_value}". '
        "Please provide it exactly as it appears in your data."
    )


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _normalized_query_text(question: str) -> str:
    return normalize_lookup_text(question) or question.lower()


@dataclass(frozen=True)
class QuerySlots:
    top_n: int | None = None
    group_by: str | None = None
    metric: str | None = None
    entity: str | None = None
    source: str | None = None
    courier: str | None = None
    location: str | None = None
    phone_number: str | None = None


def _is_delivery_count_question(text: str) -> bool:
    normalized_text = _normalized_query_text(text)
    if _contains_any(
        text,
        (
            "delivery fee",
            "shipping fee",
            "стоимость доставки",
            "առաքման վճար",
            "առաքման գումար",
        ),
    ) or _contains_any(
        normalized_text,
        (
            "delivery fee",
            "shipping fee",
            "stoimost dostavki",
            "araqman vjar",
            "araqman gumar",
        ),
    ):
        return False
    return (
        _contains_any(
            text,
            ("delivery", "deliveries", "достав", "առաք"),
        )
        or _contains_any(
            normalized_text,
            ("delivery", "deliveries", "dostav", "araq", "araqum"),
        )
    ) and (
        _contains_any(
            text,
            (
                "how many",
                "number of",
                "count",
                "quantity",
                "total count",
                "сколько",
                "колич",
                "քանի",
                "քանակ",
            ),
        )
        or _contains_any(
            normalized_text,
            (
                "how many",
                "number of",
                "count",
                "quantity",
                "total count",
                "skolko",
                "kolich",
                "qani",
                "kani",
                "qanak",
            ),
        )
    )


def _normalize_entity_token(value: str) -> str:
    normalized = (
        value.strip()
        .lower()
        .replace("֊", "-")
        .replace("–", "-")
        .replace("—", "-")
    )
    normalized = " ".join(normalized.split())
    return normalized.removesuffix("ը").strip()


def _normalize_possessive_entity_token(value: str) -> str:
    normalized = _normalize_entity_token(value)
    if re.search(r"[\u0531-\u0556\u0561-\u0587]", normalized):
        if normalized.endswith("ի") and len(normalized) > 2:
            return normalized.removesuffix("ի").strip()
        return normalized

    for suffix in ("yi", "i", "y"):
        if normalized.endswith(suffix) and len(normalized) > len(suffix) + 2:
            return normalized[: -len(suffix)].strip()
    return normalized


def _normalize_phone_token(value: str) -> str | None:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 6 or len(digits) > 15:
        return None
    if digits.startswith("374") and len(digits) in {11, 12}:
        return f"0{digits[3:]}"
    return digits


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
    if _contains_any(
        text,
        ("by source", "source mix", "channel mix", "by channel", "по источ", "ըստ աղբյուր"),
    ):
        return "source"
    if _contains_any(
        text,
        ("by courier", "by driver", "courier split", "курьер", "ըստ առաքիչ"),
    ):
        return "courier"
    if _contains_any(text, ("by weekday", "day of week", "дням недели", "շաբաթվա օր")):
        return "weekday"
    if _contains_any(
        text,
        ("by address", "by location", "top address", "топ адрес", "ըստ հասցե"),
    ):
        return "location"
    if _contains_any(text, ("by customer", "топ клиент", "ըստ հաճախորդ")):
        return "customer"
    return None


def _extract_metric(question: str) -> str | None:
    text = question.lower()
    normalized_text = _normalized_query_text(question)
    if _contains_any(
        text,
        (
            "average check",
            "avg check",
            "average ticket",
            "average order value",
            "basket size",
            "средний чек",
            "средняя сумма заказа",
            "միջին չեկ",
            "միջին պատվերի արժեք",
        ),
    ) or _contains_any(
        normalized_text,
        (
            "average check",
            "avg check",
            "average ticket",
            "average order value",
            "basket size",
            "srednii chek",
            "mijin chek",
            "mijin patveri arzheq",
        ),
    ):
        return "average_check"
    if _contains_any(
        text,
        (
            "gross profit",
            "gross margin",
            "margin",
            "валовая прибыль",
            "валовая маржа",
            "համախառն շահույթ",
            "մարժա",
        ),
    ) or _contains_any(
        normalized_text,
        (
            "gross profit",
            "gross margin",
            "margin",
            "valovaia pribyl",
            "hamakharhn shahrut",
            "marzha",
        ),
    ):
        return "gross_profit"
    if _is_delivery_count_question(text):
        return "order_count"
    if _contains_any(text, ("order count", "number of orders", "сколько заказ", "քանի պատվ")):
        return "order_count"
    if _contains_any(
        text,
        (
            "total sales",
            "total revenue",
            "revenue",
            "turnover",
            "sales amount",
            "общие продажи",
            "выручка",
            "оборот",
            "ընդհանուր վաճառ",
            "շրջանառություն",
        ),
    ) or _contains_any(
        normalized_text,
        (
            "total sales",
            "total revenue",
            "revenue",
            "turnover",
            "sales amount",
            "obshchie prodazhi",
            "viruchka",
            "yndhanur vachar",
            "shrjanarutiun",
        ),
    ):
        return "sales_total"
    if _contains_any(
        text,
        ("collection rate", "paid vs invoiced", "собираемость", "հավաքագրման տոկոս"),
    ) or _contains_any(
        normalized_text,
        ("collection rate", "paid vs invoiced", "sobiraemost", "havaqagrman tokos"),
    ):
        return "payment_collection"
    if _contains_any(text, ("outstanding balance", "задолж", "չմարված")) or _contains_any(
        normalized_text,
        ("outstanding balance", "zadolzh", "chmardz"),
    ):
        return "outstanding_balance"
    if _contains_any(text, ("repeat customer", "повторн", "կրկնվող հաճախ")) or _contains_any(
        normalized_text,
        ("repeat customer", "povtorn", "krknvogh hach"),
    ):
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
    source_match = re.search(
        r"(?:source|channel|platform|источник|աղբյուր)\s*(?:[:=]\s*|\s+)"
        r"([^\n,.;!?]+?)(?=\s+\d{4}-\d{2}-\d{2}\b|$|[,.!?;])",
        question,
        re.IGNORECASE,
    )
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


def _extract_courier_filter(question: str) -> str | None:
    explicit_match = re.search(
        r"(?:courier|driver|kurier|araqich|курьер|առաքիչ)\s*(?:[:=]\s*|\s+)"
        r"([^\n,.;!?]+?)(?=\s+\d{4}-\d{2}-\d{2}\b|$|[,.!?;])",
        question,
        re.IGNORECASE,
    )
    if explicit_match is not None:
        candidate = _normalize_entity_token(explicit_match.group(1))
        return candidate or None

    trailing_name_match = re.search(
        r"^\s*([A-Za-z\u0531-\u0556\u0561-\u0587]{2,})\s*(?:ը)?\s+քանի\s+հատ\s+առաք",
        question.lower(),
    )
    if trailing_name_match is not None:
        candidate = _normalize_entity_token(trailing_name_match.group(1))
        return candidate or None

    if _is_delivery_count_question(question):
        leading_armenian_possessive_match = re.search(
            r"^\s*([A-Za-z\u0531-\u0556\u0561-\u0587]{2,}(?:ի|i|y))\b.*?(?:առաք|delivery|достав)",
            question.lower(),
        )
        if leading_armenian_possessive_match is not None:
            candidate = _normalize_possessive_entity_token(
                leading_armenian_possessive_match.group(1)
            )
            return candidate or None

    normalized_question = _normalized_query_text(question)
    translit_leading_match = re.search(
        r"^\s*([a-z][a-z0-9_-]{1,})\s+(?:qani|kani)\s+(?:hat\s+)?araq",
        normalized_question,
    )
    if translit_leading_match is not None:
        candidate = _normalize_entity_token(translit_leading_match.group(1))
        return candidate or None

    if _is_delivery_count_question(question):
        translit_possessive_match = re.search(
            r"^\s*([a-z][a-z0-9_-]{1,}(?:yi|i|y))\b.*?(?:araq|delivery|dostav)",
            normalized_question,
        )
        if translit_possessive_match is not None:
            candidate = _normalize_possessive_entity_token(translit_possessive_match.group(1))
            return candidate or None

        translit_trailing_match = re.search(
            r"(?:arel|eghel|made|done)\s+([a-z][a-z0-9_-]{1,})\s*$",
            normalized_question,
        )
        if translit_trailing_match is not None:
            candidate = _normalize_entity_token(translit_trailing_match.group(1))
            return candidate or None

    return None


def _extract_location_filter(question: str) -> str | None:
    explicit_match = re.search(
        r"(?:address|location|адрес|локац|հասցե)\s*(?:[:=]\s*|\s+)"
        r"([^\n,.;!?]+?)(?=\s+\d{4}-\d{2}-\d{2}\b|$|[,.!?;])",
        question,
        re.IGNORECASE,
    )
    if explicit_match is not None:
        candidate = _normalize_entity_token(explicit_match.group(1))
        return candidate or None

    locative_match = re.search(
        r"([A-Za-z\u0531-\u0556\u0561-\u05870-9\-\s]{3,}?)\s*[֊\-]?ում\b",
        question,
    )
    if locative_match is None:
        return None

    candidate = _normalize_entity_token(locative_match.group(1))
    if not candidate:
        return None

    if any(ch.isdigit() for ch in candidate):
        return candidate

    if _contains_any(candidate, ("street", "ave", "просп", "փողոց", "ул.")):
        return candidate

    return None


def _extract_phone_filter(question: str) -> str | None:
    explicit_match = re.search(
        r"(?:phone|tel|mobile|հեռախոս|номер)\s*(?:[:=]\s*|\s+)?([+\d\-\s()]{6,24})",
        question,
        re.IGNORECASE,
    )
    if explicit_match is not None:
        return _normalize_phone_token(explicit_match.group(1))

    contextual_match = re.search(
        r"(\+?\d[\d\-\s()]{5,20}\d)\s*(?:համար(?:ից)?|phone|tel|номер(?:а)?)",
        question,
        re.IGNORECASE,
    )
    if contextual_match is not None:
        return _normalize_phone_token(contextual_match.group(1))

    return None


def _extract_query_slots(question: str) -> QuerySlots:
    return QuerySlots(
        top_n=_extract_top_n(question),
        group_by=_extract_group_by(question),
        metric=_extract_metric(question),
        entity=_extract_entity(question),
        source=_extract_source_filter(question),
        courier=_extract_courier_filter(question),
        location=_extract_location_filter(question),
        phone_number=_extract_phone_filter(question),
    )


def _detect_report_candidates(question: str) -> list[ReportType]:
    text = question.lower()
    candidates: list[ReportType] = []
    delivery_count_question = _is_delivery_count_question(text)

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
            "margin",
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
    if delivery_count_question:
        add(ReportType.ORDER_COUNT)
    if (not delivery_count_question) and _contains_any(
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
            "by driver",
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
            "by channel",
            "by platform",
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
            "average order value",
            "basket size",
            "средний чек",
            "средняя сумма заказа",
            "միջին չեկ",
            "միջին պատվերի արժեք",
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
            "revenue",
            "turnover",
            "sales amount",
            "общие продажи",
            "выручка",
            "оборот",
            "ընդհանուր վաճառ",
            "շրջանառություն",
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
    if slots.phone_number is not None:
        return ReportType.ORDER_COUNT

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
    def add_candidate(
        report_id: ReportType,
        *,
        candidates: list[ReportType],
    ) -> None:
        if report_id not in candidates:
            candidates.append(report_id)

    segments = [
        segment.strip(" ,.;!?")
        for segment in re.split(
            r"\s+(?:and|plus|also|as well as|&|և|ու|и|а также)\s+",
            question,
            flags=re.IGNORECASE,
        )
        if segment.strip(" ,.;!?")
    ]

    candidates: list[ReportType] = []
    if len(segments) > 1:
        for segment in segments:
            segment_candidates = _detect_report_candidates(segment)
            if not segment_candidates:
                mapped = _map_slots_to_report(_extract_query_slots(segment))
                if mapped is not None:
                    segment_candidates = [mapped]
            for report_id in segment_candidates:
                add_candidate(report_id, candidates=candidates)

    if not candidates:
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
    if _detect_report_id(question) is not None:
        return False
    if _has_explicit_or_relative_time_signal(question):
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


def _quarter_start(day: date) -> date:
    quarter_start_month = ((day.month - 1) // 3) * 3 + 1
    return date(day.year, quarter_start_month, 1)


def _previous_quarter_range(day: date) -> tuple[date, date]:
    current_quarter_start = _quarter_start(day)
    previous_quarter_end = current_quarter_start - timedelta(days=1)
    previous_quarter_start = _quarter_start(previous_quarter_end)
    return previous_quarter_start, previous_quarter_end


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


def _default_report_filters() -> ReportFilters | None:
    settings = get_settings()
    excel_path = settings.excel_report_file_path
    if excel_path and excel_path.strip():
        path = Path(excel_path)
        if path.exists():
            try:
                date_from, date_to = get_excel_data_date_range(
                    path,
                    sheet_name=settings.excel_report_sheet_name,
                )
            except Exception:
                pass
            else:
                return _build_filters(date_from, date_to)

    date_from, date_to = get_mock_data_date_range()
    return _build_filters(date_from, date_to)


def _extract_relative_filters_from_normalized_text(
    normalized_text: str,
    *,
    today: date,
) -> ReportFilters | None:
    if not normalized_text:
        return None

    def rolling_pattern(markers: tuple[str, ...], unit_pattern: str) -> str:
        marker_pattern = "|".join(re.escape(marker) for marker in markers)
        return rf"\b(?:{marker_pattern})\s+(?P<n>\d{{1,3}})\s+{unit_pattern}\b"

    def anchored_pattern(markers: tuple[str, ...], unit_pattern: str) -> str:
        marker_pattern = "|".join(re.escape(marker) for marker in markers)
        return rf"\b(?:{marker_pattern})\s+{unit_pattern}\b"

    today_markers = ("today", "aysor")
    yesterday_markers = ("yesterday", "erek")
    this_markers = ("this", "current", "ays", "es")
    last_markers = ("last", "previous", "nakhord", "ancats")
    rolling_markers = ("last", "past", "verjin")

    day_unit = r"(?:days?|or[a-z]*)"
    week_unit = r"(?:weeks?|shabat[a-z]*)"
    month_unit = r"(?:months?|am(?:is|s)[a-z]*)"
    quarter_unit = r"(?:quarters?|eramsyak[a-z]*)"
    year_unit = r"(?:years?|tar(?:i|va)[a-z]*)"

    for pattern, duration_builder in (
        (
            rolling_pattern(rolling_markers, day_unit),
            lambda count: _build_filters(today - timedelta(days=count - 1), today),
        ),
        (
            rolling_pattern(rolling_markers, week_unit),
            lambda count: _build_filters(today - timedelta(days=7 * count - 1), today),
        ),
        (
            rolling_pattern(rolling_markers, month_unit),
            lambda count: _build_filters(
                _shift_month_start(_first_day_of_month(today), -(count - 1)),
                today,
            ),
        ),
        (
            rolling_pattern(rolling_markers, year_unit),
            lambda count: _build_filters(date(today.year - (count - 1), 1, 1), today),
        ),
    ):
        match = re.search(pattern, normalized_text)
        if match is None:
            continue
        count = int(match.group("n"))
        if count <= 0:
            return None
        return duration_builder(count)

    if any(_contains_text_term(normalized_text, marker) for marker in today_markers):
        return _build_filters(today, today)
    if any(_contains_text_term(normalized_text, marker) for marker in yesterday_markers):
        previous_day = today - timedelta(days=1)
        return _build_filters(previous_day, previous_day)

    if re.search(anchored_pattern(this_markers, week_unit), normalized_text):
        this_week_start = today - timedelta(days=today.weekday())
        return _build_filters(this_week_start, today)
    if re.search(anchored_pattern(last_markers, week_unit), normalized_text):
        this_week_start = today - timedelta(days=today.weekday())
        last_week_end = this_week_start - timedelta(days=1)
        last_week_start = last_week_end - timedelta(days=6)
        return _build_filters(last_week_start, last_week_end)

    if re.search(anchored_pattern(this_markers, month_unit), normalized_text):
        return _build_filters(_first_day_of_month(today), today)
    if re.search(anchored_pattern(last_markers, month_unit), normalized_text):
        this_month_start = _first_day_of_month(today)
        last_month_end = this_month_start - timedelta(days=1)
        last_month_start = _first_day_of_month(last_month_end)
        return _build_filters(last_month_start, last_month_end)

    if re.search(anchored_pattern(this_markers, quarter_unit), normalized_text):
        return _build_filters(_quarter_start(today), today)
    if re.search(anchored_pattern(last_markers, quarter_unit), normalized_text):
        quarter_start, quarter_end = _previous_quarter_range(today)
        return _build_filters(quarter_start, quarter_end)

    if re.search(anchored_pattern(this_markers, year_unit), normalized_text):
        return _build_filters(date(today.year, 1, 1), today)
    if re.search(anchored_pattern(last_markers, year_unit), normalized_text):
        return _build_filters(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31))

    if (
        "all time" in normalized_text
        or "entire history" in normalized_text
        or re.search(r"\b(?:bolor|amboxj)\s+(?:jamanak|patmut[a-z]*)\b", normalized_text)
    ):
        return _default_report_filters()

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
        r"վերջին\s+(?P<n>\d{1,3})\s+ամ(?:իս|ս)(?:վա|ների)?",
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
        (
            "this quarter",
            "current quarter",
            "этот квартал",
            "текущий квартал",
            "այս եռամսյակ",
        ),
    ):
        return _build_filters(_quarter_start(today), today)
    if _contains_any(
        text,
        (
            "last quarter",
            "previous quarter",
            "прошлый квартал",
            "предыдущий квартал",
            "նախորդ եռամսյակ",
        ),
    ):
        quarter_start, quarter_end = _previous_quarter_range(today)
        return _build_filters(quarter_start, quarter_end)

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
            "նախորդ տարվա",
            "անցած տարի",
            "անցած տարվա",
        ),
    ):
        return _build_filters(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31))

    normalized_text = normalize_lookup_text(question) or ""
    return _extract_relative_filters_from_normalized_text(normalized_text, today=today)


def _extract_filters(
    question: str,
    *,
    default_to_all_time: bool = True,
) -> ReportFilters | None:
    match = _DATE_RANGE_PATTERN.search(question)
    if match is not None:
        try:
            date_from = date.fromisoformat(match.group(1))
            date_to = date.fromisoformat(match.group(2))
            return ReportFilters(date_from=date_from, date_to=date_to)
        except ValueError:
            return None

    relative_filters = _extract_relative_filters(question, today=_today())
    if relative_filters is not None:
        return relative_filters
    if default_to_all_time:
        return _default_report_filters()
    return None


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

    explicit_date_range = _DATE_RANGE_PATTERN.search(question) is not None
    filters = _extract_filters(question)
    if filters is None and explicit_date_range:
        return {
            "intent": IntentType.NEEDS_CLARIFICATION,
            "report_id": selected_report_id,
            "filters": None,
            "needs_clarification": True,
            "clarification_question": "Please provide a valid date "
                                      "range using YYYY-MM-DD to YYYY-MM-DD.",
            "confidence": 0.55,
            "reasoning_notes": "An explicit date range was present but could not be parsed safely.",
        }
    if filters is None:
        filters = _default_report_filters()

    filter_updates: dict[str, str] = {}
    if slots.source:
        filter_updates["source"] = slots.source
    if slots.courier:
        filter_updates["courier"] = slots.courier
    if slots.location:
        filter_updates["location"] = slots.location
    if slots.phone_number:
        filter_updates["phone_number"] = slots.phone_number
    if filter_updates:
        filters = _strip_incompatible_filters(
            selected_report_id,
            filters.model_copy(update=filter_updates),
        ) or filters

    intent = (
        IntentType.BREAKDOWN_KPI
        if selected_report_id in _BREAKDOWN_REPORT_IDS
        else IntentType.GET_KPI
    )
    used_all_time_default = not _has_explicit_or_relative_time_signal(question)
    return {
        "intent": intent,
        "report_id": selected_report_id,
        "filters": filters,
        "needs_clarification": False,
        "clarification_question": None,
        "confidence": 0.82 if used_all_time_default else 0.9,
        "reasoning_notes": (
            (
                "Report identified with deterministic slot extraction and all-time default "
                "date range: "
                if used_all_time_default
                else "Report and filters identified with deterministic slot extraction: "
            )
            + f"group_by={slots.group_by}, metric={slots.metric}, entity={slots.entity}, "
            + f"top_n={slots.top_n}, source={slots.source}, courier={slots.courier}, "
            + f"location={slots.location}, phone_number={slots.phone_number}."
        ),
    }


def _should_query_llm(
    deterministic_payload: dict[str, Any],
    *,
    slots: QuerySlots,
    additional_report_ids: list[ReportType],
) -> bool:
    intent = deterministic_payload.get("intent")
    if intent in {IntentType.UNSUPPORTED_REQUEST, IntentType.NEEDS_CLARIFICATION}:
        return True
    if additional_report_ids:
        return True
    return any(
        value is not None
        for value in (
            slots.group_by,
            slots.entity,
            slots.source,
            slots.courier,
            slots.location,
            slots.phone_number,
        )
    )


def _interpret_request_with_llm(
    question: str,
    llm_client: Any,
) -> dict[str, Any]:
    messages = build_interpret_request_messages(question, current_date=_today())
    output_text = llm_client.generate_text(messages=messages)
    interpretation = parse_interpretation_output_json(output_text)
    return interpretation.model_dump(mode="python")


def _select_interpretation(
    deterministic: Any,
    llm_output: Any | None,
) -> Any:
    if llm_output is None:
        return deterministic

    deterministic_executable = (
        deterministic.intent in {IntentType.GET_KPI, IntentType.BREAKDOWN_KPI}
        and not deterministic.needs_clarification
        and deterministic.report_id is not None
        and deterministic.filters is not None
    )
    llm_executable = (
        llm_output.intent in {IntentType.GET_KPI, IntentType.BREAKDOWN_KPI}
        and not llm_output.needs_clarification
        and llm_output.report_id is not None
        and llm_output.filters is not None
    )

    if not deterministic_executable and llm_executable:
        return llm_output
    if deterministic_executable and not llm_executable:
        return deterministic
    if not deterministic_executable and not llm_executable:
        if (
            deterministic.intent is IntentType.UNSUPPORTED_REQUEST
            and llm_output.intent is not IntentType.UNSUPPORTED_REQUEST
        ):
            return llm_output
        return deterministic
    if llm_output.report_id != deterministic.report_id:
        return deterministic
    if _non_null_filter_count(llm_output.filters) > _non_null_filter_count(deterministic.filters):
        return llm_output
    if llm_output.confidence >= deterministic.confidence + 0.1:
        return llm_output
    return deterministic


def _resolvable_filter_values(
    report_id: ReportType,
    filters: ReportFilters,
) -> list[tuple[ReportFilterKey, str, str]]:
    return [
        (filter_key, field_name, raw_value)
        for filter_key, field_name in _FILTER_FIELD_BY_KEY.items()
        if filter_key in _optional_filter_keys(report_id)
        and (raw_value := getattr(filters, field_name)) is not None
    ]


def _resolve_filter_value_with_llm(
    state: AgentState,
    *,
    filter_key: ReportFilterKey,
    raw_value: str,
    candidates: list[str],
) -> str | None:
    if not candidates or filter_key is ReportFilterKey.PHONE_NUMBER:
        return None

    try:
        llm_client = get_llm_client()
    except ValueError:
        return None

    try:
        output_text = llm_client.generate_text(
            messages=build_filter_match_messages(
                user_question=state.user_question,
                filter_key=filter_key.value,
                raw_value=raw_value,
                candidates=candidates,
            )
        )
        resolution = parse_filter_match_output_json(output_text, candidates=candidates)
    except (LLMClientError, FilterMatchContractError):
        return None

    if resolution.matched_value is None:
        return None
    if resolution.confidence < _FILTER_MATCH_CONFIDENCE_THRESHOLD:
        return None
    return resolution.matched_value


def _resolve_report_filters(state: AgentState) -> dict[str, Any]:
    report_id = state.selected_report_id
    filters = state.filters
    if report_id is None or filters is None:
        return {}

    resolved_filters = filters
    warnings = [*state.warnings]
    for filter_key, field_name, raw_value in _resolvable_filter_values(report_id, filters):
        try:
            resolution_response = resolve_filter_value_tool(
                ResolveFilterValueRequest(
                    report_id=report_id,
                    filter_key=filter_key,
                    raw_value=raw_value,
                )
            )
        except Exception:
            return {
                "status": RunStatus.FAILED,
                "final_answer": _localized_message(state, "run_failed_internal"),
                "warnings": [*warnings, "filter_resolution_failed"],
            }

        if (
            resolution_response.status is ResolveFilterValueStatus.RESOLVED
            and resolution_response.matched_value is not None
        ):
            resolved_filters = resolved_filters.model_copy(
                update={field_name: resolution_response.matched_value}
            )
            continue

        llm_matched_value = _resolve_filter_value_with_llm(
            state,
            filter_key=filter_key,
            raw_value=raw_value,
            candidates=resolution_response.candidates,
        )
        if llm_matched_value is not None:
            resolved_filters = resolved_filters.model_copy(
                update={field_name: llm_matched_value}
            )
            warnings.append(f"{_FILTER_RESOLUTION_LLM_WARNING}:{filter_key.value}")
            continue

        return {
            "status": RunStatus.CLARIFY,
            "filters": resolved_filters,
            "warnings": warnings,
            "needs_clarification": True,
            "clarification_question": _build_filter_clarification_question(
                state,
                filter_key=filter_key,
                raw_value=raw_value,
                candidates=resolution_response.candidates,
            ),
        }

    return {
        "filters": resolved_filters,
        "warnings": warnings,
    }


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
        deterministic_output = validate_interpretation_output(deterministic_interpretation)
        llm_output = None
        if _should_query_llm(
            deterministic_interpretation,
            slots=slots,
            additional_report_ids=additional_report_ids,
        ):
            try:
                llm_client = get_llm_client()
            except ValueError:
                llm_output = None
            else:
                try:
                    llm_output = validate_interpretation_output(
                        _interpret_request_with_llm(
                            state.user_question,
                            llm_client,
                        )
                    )
                except InterpretationContractError:
                    llm_output = None
                    warnings.append("llm_interpretation_contract_invalid")
                except LLMClientError as exc:
                    llm_output = None
                    warnings.append(
                        _INTERPRET_RATE_LIMIT_FALLBACK_WARNING
                        if exc.category is LLMErrorCategory.RATE_LIMIT
                        else _INTERPRET_LLM_FALLBACK_WARNING
                    )

        interpretation = _select_interpretation(deterministic_output, llm_output)
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

    interpretation_filters = _strip_incompatible_filters(
        interpretation.report_id,
        interpretation.filters,
    )

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

    filter_resolution_update = _resolve_report_filters(state)
    if filter_resolution_update.get("status") in {
        RunStatus.CLARIFY,
        RunStatus.FAILED,
    }:
        return filter_resolution_update

    return {
        **filter_resolution_update,
        "status": RunStatus.RUNNING,
    }


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
        return _strip_incompatible_filters(report_id, filters) or filters

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


def _small_talk_fallback_response(state: AgentState) -> str:
    language = _response_language(state.user_question)
    normalized_question = normalize_lookup_text(state.user_question) or ""
    capability_text = _join_human_list(
        state,
        [
            _localized_report_name(state, ReportType.SALES_TOTAL),
            _localized_report_name(state, ReportType.ORDER_COUNT),
            _localized_report_name(state, ReportType.TOP_CUSTOMERS),
            _localized_report_name(state, ReportType.PAYMENT_COLLECTION),
            _localized_report_name(state, ReportType.DAILY_SALES_TREND),
        ],
    )

    if any(
        _contains_text_term(normalized_question, term)
        for term in ("thanks", "thank you", "thx", "spasibo", "shnorhakal", "shnorhakalutyun")
    ):
        response_message = (f"You're welcome. I can also help with "
                            f"restaurant analytics such as {capability_text}.")
        if language == "hy":
            response_message = f"Խնդրեմ։ Կարող եմ օգնել նաև {capability_text} հարցերով։"
        if language == "ru":
            response_message = (f"Пожалуйста. Я также могу помочь с "
                                f"аналитикой по темам: {capability_text}.")
        return response_message

    if any(
        _contains_text_term(normalized_question, term)
        for term in ("how are you", "inchpes es", "vonc es", "kak dela")
    ):
        if language == "hy":
            return f"Լավ եմ, պատրաստ եմ օգնելու։ Կարող եք հարցնել {capability_text} մասին։"
        if language == "ru":
            return f"Все в порядке, готов помочь. Можете спросить про {capability_text}."
        return f"I'm ready to help. You can ask about {capability_text}."

    if language == "hy":
        return f"Բարև։ Կարող եմ օգնել {capability_text} վերաբերյալ վերլուծություններով։"
    if language == "ru":
        return f"Здравствуйте. Я могу помочь с аналитикой по темам: {capability_text}."
    return f"Hi. I can help with restaurant analytics such as {capability_text}."


def _generate_small_talk_response(state: AgentState) -> tuple[str, list[str]]:
    try:
        llm_client = get_llm_client()
    except ValueError:
        return _small_talk_fallback_response(state), state.warnings

    try:
        response = llm_client.generate_text(
            messages=build_small_talk_messages(state.user_question)
        ).strip()
    except LLMClientError:
        return _small_talk_fallback_response(state), [*state.warnings, "small_talk_llm_fallback"]

    if not response:
        return _small_talk_fallback_response(state), [*state.warnings, "small_talk_llm_empty"]
    return response, state.warnings


def _clarify_node(state: AgentState) -> dict[str, Any]:
    question = _localized_clarification_question(state)
    return {
        "status": RunStatus.CLARIFY,
        "final_answer": question,
        "needs_clarification": True,
        "clarification_question": question,
    }


def _small_talk_node(state: AgentState) -> dict[str, Any]:
    final_answer, warnings = _generate_small_talk_response(state)
    return {
        "status": RunStatus.COMPLETED,
        "final_answer": final_answer,
        "warnings": warnings,
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


def _metric_value_fragment(
    state: AgentState,
    metric_key: str,
    value: Any,
    *,
    capitalize: bool = False,
) -> str:
    label = _localized_metric_label(state, metric_key)
    formatted_value = _format_numeric_value(value, as_percentage=_is_percentage_metric(metric_key))
    language = _response_language(state.user_question)
    separator = "՝" if language == "hy" else ":"
    fragment = f"{label}{separator} {formatted_value}"
    if capitalize:
        return _capitalize_first(fragment)
    return fragment


def _metric_not_available_fragment(state: AgentState, metric_key: str) -> str:
    label = _localized_metric_label(state, metric_key)
    language = _response_language(state.user_question)
    if language == "hy":
        return f"{label} հասանելի չէ"
    if language == "ru":
        return f"{label} недоступно"
    return f"{label} was not available"


def _breakdown_metric_fragment(
    state: AgentState,
    *,
    report_id: ReportType,
    label: str,
    value: Any,
) -> str:
    display_label = _display_dimension_value(state, label)
    display_value = _format_numeric_value(value)
    separator = "՝" if _response_language(state.user_question) == "hy" else ":"
    return f"{display_label}{separator} {display_value}"


def _compose_report_body(
    state: AgentState,
    *,
    report_id: ReportType,
    metrics: list[Any],
) -> str:
    if report_id in _BREAKDOWN_REPORT_IDS:
        details = _compact_join(
            [
                _breakdown_metric_fragment(
                    state,
                    report_id=report_id,
                    label=metric.label,
                    value=metric.value,
                )
                for metric in metrics
            ],
        )
        report_name = _localized_report_name(state, report_id)
        separator = "՝" if _response_language(state.user_question) == "hy" else ":"
        return f"{_capitalize_first(report_name)}{separator} {details}"

    return _compact_join(
        [
            _metric_value_fragment(
                state,
                metric.label,
                metric.value,
                capitalize=index == 0,
            )
            for index, metric in enumerate(metrics)
        ]
    )


def _wrap_period_summary(state: AgentState, filters: ReportFilters, body: str) -> str:
    context_phrase = _filter_context_phrase(state, filters)
    language = _response_language(state.user_question)
    if language == "en":
        period = f" ({filters.date_from} to {filters.date_to})"
    else:
        period = f" ({filters.date_from} - {filters.date_to})"

    if context_phrase:
        if language == "hy":
            return f"{context_phrase}, {body}{period}։"
        if language == "ru":
            return f"{context_phrase}, {body}{period}."
        return f"{_capitalize_first(context_phrase)}, {body}{period}."

    if language == "hy":
        return f"{body}{period}։"
    return f"{body}{period}."


def _format_derived_metrics(state: AgentState) -> str:
    if not state.derived_metrics:
        return ""

    language = _response_language(state.user_question)
    parts = [
        (
            (
                f"Օրական միջինը՝ {_format_numeric_value(metric.value)}"
                if language == "hy" and metric.key == "sales_total_per_day"
                else f"В среднем в день {_format_numeric_value(metric.value)}"
                if language == "ru" and metric.key == "sales_total_per_day"
                else f"Per day: {_format_numeric_value(metric.value)}"
                if language == "en" and metric.key == "sales_total_per_day"
                else f"Օրական միջինը՝ {_format_numeric_value(metric.value)} պատվեր"
                if language == "hy" and metric.key == "order_count_per_day"
                else f"В среднем в день {_format_numeric_value(metric.value)} заказов"
                if language == "ru" and metric.key == "order_count_per_day"
                else f"Per day: {_format_numeric_value(metric.value)} orders"
                if language == "en" and metric.key == "order_count_per_day"
                else _metric_value_fragment(
                    state,
                    metric.key,
                    metric.value,
                    capitalize=False,
                )
            )
            if metric.value is not None
            else _metric_not_available_fragment(state, metric.key)
        )
        for metric in state.derived_metrics
    ]
    joined = _compact_join(parts)
    if language == "hy":
        return f"{joined}։"
    return f"{joined}."


def _compose_single_report_summary(
    state: AgentState,
    *,
    report_id: ReportType,
    filters: ReportFilters,
    metrics: list[Any],
    include_derived: bool,
) -> str:
    display_metrics = _metrics_for_display(report_id, metrics, state.requested_top_n)
    sentences = [
        _wrap_period_summary(
            state,
            filters,
            _compose_report_body(state, report_id=report_id, metrics=display_metrics),
        )
    ]

    if include_derived:
        derived_sentence = _format_derived_metrics(state)
        if derived_sentence:
            sentences.append(derived_sentence)

    return " ".join(sentences)


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
        include_derived=False,
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
        final_answer = "\n\n".join(blocks)

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
