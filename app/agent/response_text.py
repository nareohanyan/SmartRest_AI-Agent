from __future__ import annotations

import re
from enum import Enum
from decimal import Decimal
from typing import Any

from app.schemas.analysis import (
    BreakdownItem,
    BusinessQuerySpec,
    DimensionName,
    ItemPerformanceMetric,
    ItemPerformanceResponse,
    MetricName,
    RankingMode,
    TimeseriesPoint,
)
from app.schemas.reports import ReportResult, ReportType

_ARMENIAN_CHAR_RE = re.compile(r"[\u0531-\u058F]")
_CYRILLIC_CHAR_RE = re.compile(r"[\u0400-\u04FF]")
_MONEY_KEYS = {
    "sales_total",
    "gross_sales_total",
    "average_check",
    "discount_amount",
    "refund_amount",
    "item_revenue",
}
_PERCENT_KEYS = {
    "discounted_order_share",
    "refund_rate",
    "discount_share",
}
_COUNT_KEYS = {
    "order_count",
    "completed_order_count",
    "discounted_order_count",
    "canceled_order_count",
    "delivery_order_count",
    "dine_in_order_count",
    "quantity_sold",
    "items_per_order",
}
_METRIC_LABELS: dict[str, dict[str, str]] = {
    "sales_total": {"hy": "ընդհանուր վաճառք", "ru": "общие продажи", "en": "total sales"},
    "gross_sales_total": {
        "hy": "համախառն վաճառք",
        "ru": "валовые продажи",
        "en": "gross sales",
    },
    "order_count": {
        "hy": "պատվերների քանակ",
        "ru": "количество заказов",
        "en": "order count",
    },
    "average_check": {"hy": "միջին չեկ", "ru": "средний чек", "en": "average check"},
    "quantity_sold": {"hy": "վաճառված քանակ", "ru": "проданное количество", "en": "quantity sold"},
    "items_per_order": {
        "hy": "մեկ պատվերի միջին ապրանքների քանակ",
        "ru": "среднее количество позиций в заказе",
        "en": "items per order",
    },
    "discounted_order_count": {
        "hy": "զեղչված պատվերների քանակ",
        "ru": "количество заказов со скидкой",
        "en": "discounted order count",
    },
    "discounted_order_share": {
        "hy": "զեղչված պատվերների մասնաբաժին",
        "ru": "доля заказов со скидкой",
        "en": "discounted order share",
    },
    "discount_amount": {"hy": "զեղչի գումար", "ru": "сумма скидки", "en": "discount amount"},
    "refund_amount": {"hy": "վերադարձի գումար", "ru": "сумма возврата", "en": "refund amount"},
    "refund_rate": {"hy": "վերադարձների մասնաբաժին", "ru": "доля возвратов", "en": "refund rate"},
    "delivery_order_count": {
        "hy": "առաքման պատվերների քանակ",
        "ru": "количество доставок",
        "en": "delivery order count",
    },
    "dine_in_order_count": {
        "hy": "սրահի պատվերների քանակ",
        "ru": "количество заказов в зале",
        "en": "dine-in order count",
    },
    "completed_order_count": {
        "hy": "ավարտված պատվերների քանակ",
        "ru": "количество завершенных заказов",
        "en": "completed order count",
    },
}
_METRIC_SUBJECT_LABELS_HY = {
    "sales_total": "ընդհանուր վաճառքը",
    "gross_sales_total": "համախառն վաճառքը",
    "order_count": "պատվերների քանակը",
    "average_check": "միջին չեկը",
    "quantity_sold": "վաճառված քանակը",
    "items_per_order": "մեկ պատվերի միջին ապրանքների քանակը",
    "discounted_order_count": "զեղչված պատվերների քանակը",
    "discounted_order_share": "զեղչված պատվերների մասնաբաժինը",
    "discount_amount": "զեղչի գումարը",
    "refund_amount": "վերադարձի գումարը",
    "refund_rate": "վերադարձների մասնաբաժինը",
    "delivery_order_count": "առաքման պատվերների քանակը",
    "dine_in_order_count": "սրահի պատվերների քանակը",
    "completed_order_count": "ավարտված պատվերների քանակը",
}
_METRIC_CONTEXT_LABELS_HY = {
    "sales_total": "ընդհանուր վաճառքի",
    "gross_sales_total": "համախառն վաճառքի",
    "order_count": "պատվերների քանակի",
    "average_check": "միջին չեկի",
    "quantity_sold": "վաճառված քանակի",
    "items_per_order": "մեկ պատվերի միջին ապրանքների քանակի",
    "discounted_order_count": "զեղչված պատվերների քանակի",
    "discounted_order_share": "զեղչված պատվերների մասնաբաժնի",
    "discount_amount": "զեղչի գումարի",
    "refund_amount": "վերադարձի գումարի",
    "refund_rate": "վերադարձների մասնաբաժնի",
}
_DIMENSION_LABELS: dict[str, dict[str, str]] = {
    "source": {"hy": "աղբյուր", "ru": "источник", "en": "source"},
    "branch": {"hy": "մասնաճյուղ", "ru": "филиал", "en": "branch"},
    "day": {"hy": "օր", "ru": "день", "en": "day"},
    "weekday": {"hy": "շաբաթվա օր", "ru": "день недели", "en": "weekday"},
    "payment_method": {"hy": "վճարման եղանակ", "ru": "способ оплаты", "en": "payment method"},
    "category": {"hy": "կատեգորիա", "ru": "категория", "en": "category"},
    "cashier": {"hy": "գանձապահ", "ru": "кассир", "en": "cashier"},
}
_DIMENSION_CONTEXT_LABELS_HY = {
    "source": "ըստ աղբյուրի",
    "branch": "ըստ մասնաճյուղի",
    "day": "օրերի կտրվածքով",
    "weekday": "ըստ շաբաթվա օրերի",
    "payment_method": "ըստ վճարման եղանակի",
    "category": "ըստ կատեգորիայի",
    "cashier": "ըստ գանձապահի",
}
_SOURCE_LABELS = {
    "in_store": {"hy": "սրահ", "ru": "зал", "en": "in-store"},
    "takeaway": {"hy": "վերցնելու", "ru": "на вынос", "en": "takeaway"},
}
_DIRECTION_LABELS = {
    "up": {"hy": "աճող", "ru": "восходящий", "en": "upward"},
    "down": {"hy": "նվազող", "ru": "нисходящий", "en": "downward"},
    "flat": {"hy": "կայուն", "ru": "ровный", "en": "flat"},
}


def _question_language(question: str) -> str:
    if _ARMENIAN_CHAR_RE.search(question) is not None:
        return "hy"
    if _CYRILLIC_CHAR_RE.search(question) is not None:
        return "ru"
    return "en"


def _enum_value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _strip_trailing_zeroes(number_text: str) -> str:
    if "." not in number_text:
        return number_text
    return number_text.rstrip("0").rstrip(".")


def _format_decimal(
    value: Decimal | float | int,
    *,
    fraction_digits: int = 2,
    trim: bool = True,
) -> str:
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    formatted = f"{decimal_value:,.{fraction_digits}f}"
    return _strip_trailing_zeroes(formatted) if trim else formatted


def _localized_label(mapping: dict[str, dict[str, str]], key: str, language: str) -> str:
    labels = mapping.get(key)
    if labels is None:
        return key.replace("_", " ")
    return labels.get(language, labels.get("en", key.replace("_", " ")))


def _metric_label(metric: MetricName | ReportType | str, language: str) -> str:
    return _localized_label(_METRIC_LABELS, _enum_value(metric), language)


def _metric_subject_label(metric: MetricName | ReportType | str, language: str) -> str:
    key = _enum_value(metric)
    if language == "hy":
        return _METRIC_SUBJECT_LABELS_HY.get(key, _metric_label(key, language))
    base = _metric_label(key, language)
    if language == "ru":
        return base[:1].upper() + base[1:]
    return base


def _metric_context_label(metric: MetricName | str, language: str) -> str:
    key = _enum_value(metric)
    if language == "hy":
        return _METRIC_CONTEXT_LABELS_HY.get(key, _metric_label(key, language))
    return _metric_label(key, language)


def _dimension_label(dimension: DimensionName | str, language: str) -> str:
    return _localized_label(_DIMENSION_LABELS, _enum_value(dimension), language)


def _dimension_context_label(dimension: DimensionName | str, language: str) -> str:
    key = _enum_value(dimension)
    if language == "hy":
        return _DIMENSION_CONTEXT_LABELS_HY.get(key, f"ըստ {_dimension_label(key, language)}")
    if language == "ru":
        return f"по {_dimension_label(key, language)}"
    return f"by {_dimension_label(key, language)}"


def _source_label(source: str, language: str) -> str:
    normalized = source.strip().lower()
    return _localized_label(_SOURCE_LABELS, normalized, language)


def _format_metric_amount(
    *,
    metric_key: str,
    value: Decimal | float | int,
    language: str,
) -> str:
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    if metric_key in _PERCENT_KEYS or metric_key.endswith("percent_change"):
        return f"{_format_decimal(decimal_value, fraction_digits=2)}%"
    if metric_key in _MONEY_KEYS:
        suffix = " դրամ" if language == "hy" else (" драм" if language == "ru" else "")
        return f"{_format_decimal(decimal_value, fraction_digits=2)}{suffix}"
    if metric_key in _COUNT_KEYS:
        fraction_digits = 0 if decimal_value == decimal_value.to_integral_value() else 2
        return _format_decimal(decimal_value, fraction_digits=fraction_digits)
    return _format_decimal(decimal_value, fraction_digits=2)


def _format_breakdown_item_label(label: str, language: str) -> str:
    normalized = label.strip().lower()
    if normalized in _SOURCE_LABELS:
        return _source_label(normalized, language)
    return label


def _find_derived_value(
    derived_metrics: dict[str, Decimal] | list[dict[str, Any]] | list[Any],
    key: str,
) -> Decimal | None:
    if isinstance(derived_metrics, dict):
        return derived_metrics.get(key)
    for metric in derived_metrics:
        metric_key = getattr(metric, "key", None)
        metric_value = getattr(metric, "value", None)
        if metric_key == key and metric_value is not None:
            return metric_value
    return None


def _smalltalk_answer(language: str) -> str:
    if language == "hy":
        return "Ողջու՜յն։ Ինչո՞վ կարող եմ օգնել ձեզ այսօր։"
    if language == "ru":
        return "Здравствуйте. Чем я могу вам сегодня помочь?"
    return "Hello. Nice to see you here."


def _item_metric_label(
    metric: ItemPerformanceMetric,
    language: str,
    ranking_mode: RankingMode,
) -> str:
    if metric is ItemPerformanceMetric.QUANTITY_SOLD:
        return (
            (
                "ամենավաճառված ապրանքները"
                if ranking_mode is RankingMode.TOP_K
                else "ամենաքիչ վաճառված ապրանքները"
            )
            if language == "hy"
            else (
                (
                    "самые продаваемые товары"
                    if ranking_mode is RankingMode.TOP_K
                    else "наименее продаваемые товары"
                )
                if language == "ru"
                else (
                    "top selling items"
                    if ranking_mode is RankingMode.TOP_K
                    else "least selling items"
                )
            )
        )
    if metric is ItemPerformanceMetric.DISTINCT_ORDERS:
        return (
            (
                "ամենաշատ պատվիրված ապրանքները"
                if ranking_mode is RankingMode.TOP_K
                else "ամենաքիչ պատվիրված ապրանքները"
            )
            if language == "hy"
            else (
                (
                    "самые часто заказываемые товары"
                    if ranking_mode is RankingMode.TOP_K
                    else "наименее заказываемые товары"
                )
                if language == "ru"
                else (
                    "most frequently ordered items"
                    if ranking_mode is RankingMode.TOP_K
                    else "least frequently ordered items"
                )
            )
        )
    return (
        (
            "ամենաեկամտաբեր ապրանքները"
            if ranking_mode is RankingMode.TOP_K
            else "ամենաքիչ եկամուտ բերած ապրանքները"
        )
        if language == "hy"
        else (
            (
                "самые доходные товары"
                if ranking_mode is RankingMode.TOP_K
                else "товары с наименьшей выручкой"
            )
            if language == "ru"
            else (
                "highest revenue items"
                if ranking_mode is RankingMode.TOP_K
                else "lowest revenue items"
            )
        )
    )


def _format_item_value(
    *,
    metric: ItemPerformanceMetric,
    value: Decimal,
    language: str,
) -> str:
    if metric is ItemPerformanceMetric.QUANTITY_SOLD:
        quantized = int(value) if value == value.to_integral_value() else f"{value:.2f}"
        suffix = " հատ" if language == "hy" else (" шт." if language == "ru" else " units")
        return f"{quantized}{suffix}"
    if metric is ItemPerformanceMetric.DISTINCT_ORDERS:
        quantized = int(value) if value == value.to_integral_value() else f"{value:.2f}"
        suffix = (
            " պատվեր" if language == "hy" else (" заказов" if language == "ru" else " orders")
        )
        return f"{quantized}{suffix}"
    suffix = " դրամ" if language == "hy" else (" драм" if language == "ru" else "")
    return f"{value:.2f}{suffix}"


def _format_period_label(*, date_from: object, date_to: object, language: str) -> str:
    if date_from is not None and date_to is not None:
        if language == "hy":
            return f"{date_from}-ից մինչև {date_to}"
        if language == "ru":
            return f"с {date_from} по {date_to}"
        return f"from {date_from} to {date_to}"

    if language == "hy":
        return "ամբողջ հասանելի պատմության ընթացքում"
    if language == "ru":
        return "за всю доступную историю"
    return "across the full available history"


def _build_item_performance_summary(
    *,
    business_query: BusinessQuerySpec,
    response: ItemPerformanceResponse,
    language: str,
) -> str:
    period_label = _format_period_label(
        date_from=business_query.date_from,
        date_to=business_query.date_to,
        language=language,
    )
    if not response.items:
        return (
            f"{period_label} տվյալներով ապրանքներ չեն գտնվել։"
            if language == "hy"
            else (
                f"Товары не найдены {period_label}."
                if language == "ru"
                else f"No items were found {period_label}."
            )
        )

    metric_label = _item_metric_label(response.metric, language, business_query.ranking_mode)
    if language == "hy":
        if business_query.ranking_mode is RankingMode.TOP_K:
            header = f"{period_label} ժամանակահատվածում ամենաուժեղ արդյունք ունեցած {len(response.items)} {metric_label} հետևյալն են."
        else:
            header = f"{period_label} ժամանակահատվածում ամենացածր արդյունք ունեցած {len(response.items)} {metric_label} հետևյալն են."
    elif language == "ru":
        ranking_label = "топ" if business_query.ranking_mode is RankingMode.TOP_K else "последние"
        header = f"Вот {ranking_label} {len(response.items)} {metric_label} {period_label}."
    else:
        ranking_label = "top" if business_query.ranking_mode is RankingMode.TOP_K else "bottom"
        header = (
            f"Here are the {ranking_label} {len(response.items)} {metric_label} "
            f"{period_label}."
        )

    lines = [
        f"{index}. {item.name} — "
        f"{_format_item_value(metric=response.metric, value=item.value, language=language)}"
        for index, item in enumerate(response.items, start=1)
    ]
    return "\n".join([header, *lines])


def _safe_unsupported_answer(language: str) -> str:
    if language == "hy":
        return (
            "Ցավոք ես չունեմ բավականաչափ ինֆորմացիա տվյալ հարցին պատասխանելու համար։ "
            "Ավելին իմանալու համար կարող եք զանգահարել 060 44 55 66։ "
        )
    if language == "ru":
        return (
            "К сожалению, у меня недостаточно информации, чтобы ответить на этот вопрос. "
            "Для получения дополнительной информации вы можете позвонить по номеру 060 44 55 66."
        )
    return (
        "Unfortunately i don't have enough information to answer your question. "
        "For further questions you can contact 060 44 55 66."
    )


def _access_denied_answer(language: str) -> str:
    if language == "hy":
        return "Մուտքը մերժված է այս հարցման համար։"
    if language == "ru":
        return "Доступ по данному запросу запрещен."
    return "Access denied for this request."


def _build_report_result_summary(
    *,
    result: ReportResult,
    derived_metrics: dict[str, Decimal],
    language: str,
) -> str:
    metrics = {
        metric.label: Decimal(str(metric.value))
        for metric in result.metrics
    }
    period_label = _format_period_label(
        date_from=result.filters.date_from,
        date_to=result.filters.date_to,
        language=language,
    )

    if result.report_id is ReportType.SALES_TOTAL:
        sales_total = metrics.get("sales_total", Decimal("0"))
        if language == "hy":
            summary = (
                f"{period_label} {_metric_subject_label('sales_total', language)} կազմել է "
                f"{_format_metric_amount(metric_key='sales_total', value=sales_total, language=language)}։"
            )
        elif language == "ru":
            summary = (
                f"{_metric_subject_label('sales_total', language)} {period_label} составили "
                f"{_format_metric_amount(metric_key='sales_total', value=sales_total, language=language)}."
            )
        else:
            summary = (
                f"{_metric_subject_label('sales_total', language).capitalize()} {period_label} were "
                f"{_format_metric_amount(metric_key='sales_total', value=sales_total, language=language)}."
            )
        per_day = _find_derived_value(derived_metrics, "sales_total_per_day")
        if per_day is not None:
            if language == "hy":
                summary = (
                    f"{summary} Միջին օրական վաճառքը կազմել է "
                    f"{_format_metric_amount(metric_key='sales_total', value=per_day, language=language)}։"
                )
            elif language == "ru":
                summary = (
                    f"{summary} Среднее значение в день составило "
                    f"{_format_metric_amount(metric_key='sales_total', value=per_day, language=language)}."
                )
            else:
                summary = (
                    f"{summary} Average per day was "
                    f"{_format_metric_amount(metric_key='sales_total', value=per_day, language=language)}."
                )
        return summary

    if result.report_id is ReportType.ORDER_COUNT:
        order_count = metrics.get("order_count", Decimal("0"))
        summary = (
            f"{period_label} {_metric_subject_label('order_count', language)} կազմել է "
            f"{_format_metric_amount(metric_key='order_count', value=order_count, language=language)}։"
            if language == "hy"
            else (
                f"{_metric_subject_label('order_count', language)} {period_label} составило "
                f"{_format_metric_amount(metric_key='order_count', value=order_count, language=language)}."
                if language == "ru"
                else (
                    f"{_metric_subject_label('order_count', language)} {period_label} was "
                    f"{_format_metric_amount(metric_key='order_count', value=order_count, language=language)}."
                )
            )
        )
        per_day = _find_derived_value(derived_metrics, "order_count_per_day")
        if per_day is not None:
            if language == "hy":
                summary = f"{summary} Միջին օրական պատվերների քանակը կազմել է {_format_metric_amount(metric_key='order_count', value=per_day, language=language)}։"
            elif language == "ru":
                summary = f"{summary} В среднем в день было {_format_metric_amount(metric_key='order_count', value=per_day, language=language)}."
            else:
                summary = f"{summary} Average per day was {_format_metric_amount(metric_key='order_count', value=per_day, language=language)}."
        return summary

    if result.report_id is ReportType.AVERAGE_CHECK:
        average_check = metrics.get("average_check", Decimal("0"))
        if language == "hy":
            return (
                f"{period_label} {_metric_subject_label('average_check', language)} կազմել է "
                f"{_format_metric_amount(metric_key='average_check', value=average_check, language=language)}։"
            )
        if language == "ru":
            return (
                f"{_metric_subject_label('average_check', language)} {period_label} составил "
                f"{_format_metric_amount(metric_key='average_check', value=average_check, language=language)}."
            )
        return (
            f"{_metric_subject_label('average_check', language)} {period_label} was "
            f"{_format_metric_amount(metric_key='average_check', value=average_check, language=language)}."
        )

    if result.report_id is ReportType.SALES_BY_SOURCE:
        if language == "hy":
            header = f"{period_label} վաճառքն ըստ աղբյուրի հետևյալն է."
        elif language == "ru":
            header = f"Продажи по источникам {period_label}:"
        else:
            header = f"Sales by source {period_label}:"
        lines = [
            f"{index}. {_format_breakdown_item_label(metric.label, language)} — "
            f"{_format_metric_amount(metric_key='sales_total', value=metric.value, language=language)}"
            for index, metric in enumerate(result.metrics, start=1)
        ]
        return "\n".join([header, *lines])

    metrics_text = ", ".join(
        f"{metric.label}={_format_decimal(metric.value, fraction_digits=2)}"
        for metric in result.metrics
    )
    return f"{result.report_id.value}: {metrics_text}."


def _build_total_summary(
    *,
    metric: MetricName,
    value: Decimal,
    date_from: object,
    date_to: object,
    derived_metrics: list[Any],
    language: str,
) -> str:
    period_label = _format_period_label(date_from=date_from, date_to=date_to, language=language)
    metric_key = _enum_value(metric)
    amount = _format_metric_amount(metric_key=metric_key, value=value, language=language)
    if language == "hy":
        summary = f"{period_label} {_metric_subject_label(metric, language)} կազմել է {amount}։"
        per_day = _find_derived_value(derived_metrics, f"{metric_key}_per_day")
        if per_day is not None:
            summary = f"{summary} Միջին օրական ցուցանիշը կազմել է {_format_metric_amount(metric_key=metric_key, value=per_day, language=language)}։"
        return summary
    if language == "ru":
        return f"{_metric_subject_label(metric, language)} {period_label} составил {amount}."
    return f"{_metric_subject_label(metric, language).capitalize()} {period_label} was {amount}."


def _build_comparison_summary(
    *,
    metric: MetricName,
    current_value: Decimal,
    previous_value: Decimal,
    date_from: object,
    date_to: object,
    previous_date_from: object,
    previous_date_to: object,
    derived_metrics: list[Any],
    language: str,
) -> str:
    metric_key = _enum_value(metric)
    current_period = _format_period_label(date_from=date_from, date_to=date_to, language=language)
    previous_period = _format_period_label(
        date_from=previous_date_from,
        date_to=previous_date_to,
        language=language,
    )
    current_amount = _format_metric_amount(metric_key=metric_key, value=current_value, language=language)
    previous_amount = _format_metric_amount(metric_key=metric_key, value=previous_value, language=language)
    percent_change = _find_derived_value(derived_metrics, f"{metric_key}_percent_change")

    if language == "hy":
        summary = (
            f"{current_period} {_metric_subject_label(metric, language)} կազմել է {current_amount}։ "
            f"{previous_period} այն կազմել է {previous_amount}։"
        )
        if percent_change is not None:
            if percent_change > 0:
                summary = f"{summary} Նախորդ ժամանակահատվածի համեմատ այն աճել է {_format_metric_amount(metric_key=f'{metric_key}_percent_change', value=percent_change, language=language)}-ով։"
            elif percent_change < 0:
                summary = f"{summary} Նախորդ ժամանակահատվածի համեմատ այն նվազել է {_format_metric_amount(metric_key=f'{metric_key}_percent_change', value=abs(percent_change), language=language)}-ով։"
            else:
                summary = f"{summary} Նախորդ ժամանակահատվածի համեմատ այն մնացել է գրեթե անփոփոխ։"
        return summary

    if language == "ru":
        return (
            f"{_metric_subject_label(metric, language)} {current_period} составил {current_amount}, "
            f"а {previous_period} — {previous_amount}."
        )
    return (
        f"{_metric_subject_label(metric, language).capitalize()} {current_period} was {current_amount}. "
        f"For the previous period ({previous_period}) it was {previous_amount}."
    )


def _build_breakdown_summary(
    *,
    metric: MetricName,
    dimension: DimensionName,
    items: list[BreakdownItem],
    date_from: object,
    date_to: object,
    language: str,
    ranking_mode: RankingMode | None = None,
) -> str:
    period_label = _format_period_label(date_from=date_from, date_to=date_to, language=language)
    if not items:
        if language == "hy":
            return f"{period_label} տվյալներով բաշխման տվյալներ չեն գտնվել։"
        if language == "ru":
            return f"За {period_label} данные для распределения не найдены."
        return f"No breakdown data was found {period_label}."

    if language == "hy":
        context = _dimension_context_label(dimension, language)
        metric_context = _metric_context_label(metric, language)
        if ranking_mode is RankingMode.TOP_K:
            header = f"{period_label} ժամանակահատվածում {context} {metric_context} առաջատար արդյունքներն են."
        elif ranking_mode is RankingMode.BOTTOM_K:
            header = f"{period_label} ժամանակահատվածում {context} {metric_context} ամենացածր արդյունքներն են."
        else:
            header = f"{period_label} ժամանակահատվածում {context} {metric_context} բաշխումը հետևյալն է."
    elif language == "ru":
        header = f"{_metric_label(metric, language).capitalize()} {_dimension_context_label(dimension, language)} {period_label}:"
    else:
        header = f"{_metric_label(metric, language).capitalize()} {_dimension_context_label(dimension, language)} {period_label}:"

    lines = [
        f"{index}. {_format_breakdown_item_label(item.label, language)} — "
        f"{_format_metric_amount(metric_key=_enum_value(metric), value=item.value, language=language)}"
        for index, item in enumerate(items, start=1)
    ]
    return "\n".join([header, *lines])


def _build_trend_summary(
    *,
    metric: MetricName,
    points: list[TimeseriesPoint],
    date_from: object,
    date_to: object,
    moving_average_window: int | None,
    latest_moving_average: Decimal | None,
    slope_per_day: Decimal | None,
    slope_direction: str | None,
    language: str,
) -> str:
    period_label = _format_period_label(date_from=date_from, date_to=date_to, language=language)
    metric_key = _enum_value(metric)
    if not points:
        if language == "hy":
            return f"{period_label} {_metric_context_label(metric, language)} միտքի տվյալներ չեն գտնվել։"
        if language == "ru":
            return f"Для тренда {period_label} данные не найдены."
        return f"No trend data was found {period_label}."

    peak_point = max(points, key=lambda point: point.value)
    if language == "hy":
        if slope_direction is None:
            direction = "աճող" if points[-1].value > points[0].value else "նվազող" if points[-1].value < points[0].value else "կայուն"
        else:
            direction = _localized_label(_DIRECTION_LABELS, slope_direction, language)
        summary = f"{period_label} ընթացքում {_metric_context_label(metric, language)} միտքը {direction} է։"
        summary = (
            f"{summary} Ամենաբարձր արժեքը գրանցվել է {peak_point.bucket}-ին՝ "
            f"{_format_metric_amount(metric_key=metric_key, value=peak_point.value, language=language)}։"
        )
        if latest_moving_average is not None and moving_average_window is not None:
            summary = (
                f"{summary} {moving_average_window}-օրյա շարժվող միջինի վերջին արժեքը կազմել է "
                f"{_format_metric_amount(metric_key=metric_key, value=latest_moving_average, language=language)}։"
            )
        if slope_per_day is not None:
            summary = (
                f"{summary} Օրական թեքությունը կազմել է "
                f"{_format_decimal(slope_per_day, fraction_digits=4)}։"
            )
        return summary

    if language == "ru":
        return f"Тренд {_metric_label(metric, language)} {period_label} имеет { _localized_label(_DIRECTION_LABELS, slope_direction or 'flat', language)} характер."
    return f"The {_metric_label(metric, language)} trend {period_label} is {_localized_label(_DIRECTION_LABELS, slope_direction or 'flat', language)}."


def _build_customer_summary(
    *,
    date_from: object,
    date_to: object,
    unique_clients: int,
    identified_order_count: int,
    total_order_count: int,
    average_orders_per_identified_client: Decimal,
    language: str,
) -> str:
    period_label = _format_period_label(date_from=date_from, date_to=date_to, language=language)
    if language == "hy":
        return (
            f"{period_label} նույնականացված հաճախորդների քանակը կազմել է {unique_clients}։ "
            f"Նույնականացված պատվերների քանակը եղել է {identified_order_count}, "
            f"ընդհանուր պատվերների քանակը՝ {total_order_count}։ "
            f"Մեկ նույնականացված հաճախորդին միջինում բաժին է ընկել "
            f"{_format_decimal(average_orders_per_identified_client, fraction_digits=2)} պատվեր։"
        )
    if language == "ru":
        return (
            f"За {period_label} количество уникальных клиентов составило {unique_clients}, "
            f"идентифицированных заказов — {identified_order_count}, всех заказов — {total_order_count}."
        )
    return (
        f"For {period_label}, unique clients were {unique_clients}, identified orders were "
        f"{identified_order_count}, and total orders were {total_order_count}."
    )


def _build_receipt_summary(
    *,
    date_from: object,
    date_to: object,
    receipt_count: int,
    linked_order_count: int,
    status_counts: dict[str, int],
    language: str,
) -> str:
    period_label = _format_period_label(date_from=date_from, date_to=date_to, language=language)
    status_summary = ", ".join(
        f"{status}: {count}" for status, count in sorted(status_counts.items())
    )
    if language == "hy":
        summary = (
            f"{period_label} կտրոնների քանակը կազմել է {receipt_count}, "
            f"որոնցից {linked_order_count}-ը կապվել է պատվերի հետ։"
        )
        if status_summary:
            summary = f"{summary} Կարգավիճակների բաշխումը՝ {status_summary}։"
        return summary
    if language == "ru":
        return (
            f"За {period_label} количество чеков составило {receipt_count}, "
            f"из них с заказом связано {linked_order_count}. "
            f"Статусы: {status_summary or 'не найдены'}."
        )
    return (
        f"For {period_label}, receipt count was {receipt_count}, with {linked_order_count} linked "
        f"to orders. Statuses: {status_summary or 'not found'}."
    )


def _build_unsupported_task_fragment(*, user_subquery: str, language: str) -> str:
    if language == "hy":
        return f"«{user_subquery}» հարցման համար դեռ աջակցվող ցուցանիշ չգտնվեց։"
    if language == "ru":
        return f"Для запроса «{user_subquery}» пока нет поддерживаемого показателя."
    return f"I couldn't answer '{user_subquery}' because that metric is not supported yet."


def _clarification_fallback_question(language: str) -> str:
    if language == "hy":
        return "Ո՞ր տվյալն եք ուզում տեսնել։"
    if language == "ru":
        return "Пожалуйста, уточните запрос."
    return "Please clarify your request."
