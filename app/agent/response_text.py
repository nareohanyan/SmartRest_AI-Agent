from __future__ import annotations

import re
from decimal import Decimal

from app.schemas.analysis import (
    BusinessQuerySpec,
    ItemPerformanceMetric,
    ItemPerformanceResponse,
    RankingMode,
)

_ARMENIAN_CHAR_RE = re.compile(r"[\u0531-\u058F]")
_CYRILLIC_CHAR_RE = re.compile(r"[\u0400-\u04FF]")


def _question_language(question: str) -> str:
    if _ARMENIAN_CHAR_RE.search(question) is not None:
        return "hy"
    if _CYRILLIC_CHAR_RE.search(question) is not None:
        return "ru"
    return "en"


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

    ranking_label = (
        "տոփ" if business_query.ranking_mode is RankingMode.TOP_K else "վերջին"
        if language == "hy"
        else (
            "топ" if business_query.ranking_mode is RankingMode.TOP_K else "последние"
            if language == "ru"
            else "top" if business_query.ranking_mode is RankingMode.TOP_K else "bottom"
        )
    )
    metric_label = _item_metric_label(response.metric, language, business_query.ranking_mode)
    if language == "hy":
        header = f"Ահա {period_label} {ranking_label} {len(response.items)} {metric_label}։"
    elif language == "ru":
        header = f"Вот {ranking_label} {len(response.items)} {metric_label} {period_label}."
    else:
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


def _clarification_fallback_question(language: str) -> str:
    if language == "hy":
        return "Խնդրում եմ հստակեցրեք հարցումը:"
    if language == "ru":
        return "Пожалуйста, уточните запрос."
    return "Please clarify your request."
