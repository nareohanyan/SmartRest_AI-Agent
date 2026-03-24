from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from pydantic import Field, ValidationError, model_validator

from app.schemas.agent import IntentType
from app.schemas.base import SchemaModel
from app.schemas.reports import ReportFilters, ReportType

INTERPRET_REQUEST_SYSTEM_PROMPT = """
You are SmartRest's request interpretation engine.
Your job is to convert a user question into a strict reporting intent payload.

Domain scope (supported reports only):
- sales_total
- order_count
- average_check
- sales_by_source
- sales_by_courier
- top_locations
- top_customers
- repeat_customer_rate
- delivery_fee_analytics
- payment_collection
- outstanding_balance
- daily_sales_trend
- daily_order_trend
- sales_by_weekday
- gross_profit
- location_concentration

Return only one valid JSON object with this exact shape:
{
  "intent": "get_kpi" | "breakdown_kpi" | "small_talk" |
            "needs_clarification" | "unsupported_request",
  "report_id": "sales_total" | "order_count" | "average_check" | "sales_by_source" |
               "sales_by_courier" | "top_locations" | "top_customers" |
               "repeat_customer_rate" | "delivery_fee_analytics" | "payment_collection" |
               "outstanding_balance" | "daily_sales_trend" | "daily_order_trend" |
               "sales_by_weekday" | "gross_profit" | "location_concentration" | null,
  "filters": {
    "date_from": "YYYY-MM-DD",
    "date_to": "YYYY-MM-DD",
    "source": "...",
    "courier": "...",
    "location": "...",
    "phone_number": "..."
  } | null,
  "needs_clarification": boolean,
  "clarification_question": string | null,
  "confidence": number between 0 and 1,
  "reasoning_notes": string | null
}

Interpretation policy:
- Use "unsupported_request" only when the business question is outside supported reports.
- Use "small_talk" for generic conversational messages (greetings, thanks) with no analytics intent.
- Use "needs_clarification" when required filters are missing or ambiguous.
- For executable intents ("get_kpi", "breakdown_kpi"), include both report_id and full filters.
- If the question implies "by source" breakdown, use report_id "sales_by_source" and intent
  "breakdown_kpi".
- "source", "courier", "location", and "phone_number" are generic filter dimensions.
  Use them whenever the user specifies them and they are relevant to the selected report.
- If user provides a relative period (today, yesterday, this/last week, this/last month,
  this/last year, last N days/weeks/months/years), resolve to concrete date_from/date_to.
- If the user omits a time window, treat it as an all-time request instead of asking for
  clarification only because time is missing.
- Ask clarification only when the report/filter intent is ambiguous or a required filter value
  cannot be resolved safely.
- Never invent unsupported metrics, report IDs, or filter keys.
- Interpret broad business phrasing:
  sales = revenue / turnover / выручка / շրջանառություն
  average_check = average ticket / average order value / basket size
  sales_by_source = by source / by channel / by platform / source mix
  sales_by_courier = by courier / by driver
  order_count = order count / deliveries count / number of deliveries

Confidence policy:
- >= 0.85 only when report_id and required filters are explicit and unambiguous.
- 0.50-0.84 when interpretation is plausible but missing required details.
- < 0.50 when request is unsupported or highly ambiguous.

Output rules:
- Output JSON only, no markdown, no prose, no code fences.
- Do not include extra keys.
""".strip()

FILTER_MATCH_SYSTEM_PROMPT = """
You are SmartRest's filter resolution engine.
Your job is to map one raw filter mention to exactly one value from a provided candidate list.

Return only one valid JSON object with this exact shape:
{
  "matched_value": string | null,
  "confidence": number between 0 and 1,
  "reasoning_notes": string | null
}

Resolution policy:
- matched_value must be either one of the provided candidates or null.
- Prefer true equivalence across Armenian, Russian, and English scripts, transliterations,
  inflections, punctuation variants, and spacing variants.
- For phone numbers, match by digits only.
- Return null if no candidate is clearly the same value.
- Never invent a value outside the candidate list.

Confidence policy:
- >= 0.85 only when the candidate is clearly the same real-world value.
- 0.50-0.84 when one candidate looks plausible but not fully certain.
- < 0.50 when no candidate should be selected.

Output rules:
- Output JSON only, no markdown, no prose, no code fences.
- Do not include extra keys.
""".strip()

CLARIFICATION_FALLBACK_QUESTION = (
    "Please clarify which report or filter you want me to use."
)

SMALL_TALK_SYSTEM_PROMPT = """
You are SmartRest's restaurant analytics assistant.
Your job is to answer a non-analytics conversational message naturally and briefly.

Response policy:
- Reply in the same language as the user when it is clear from the message.
- Keep the answer to 1-2 short sentences.
- Sound natural, not robotic.
- You may mention that you can help with restaurant analytics such as sales, orders,
  couriers, customers, locations, payments, and trends.
- Do not invent data, metrics, or actions that were not requested.
""".strip()


class InterpretationContractError(ValueError):
    """Raised when model output violates the interpretation schema contract."""


class FilterMatchContractError(ValueError):
    """Raised when model output violates the filter-match schema contract."""


class InterpretationOutput(SchemaModel):
    intent: IntentType
    report_id: ReportType | None = None
    filters: ReportFilters | None = None
    needs_clarification: bool
    clarification_question: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_notes: str | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> InterpretationOutput:
        if self.needs_clarification and not self.clarification_question:
            raise ValueError(
                "clarification_question is required when needs_clarification is true."
            )

        if self.intent is IntentType.NEEDS_CLARIFICATION and not self.needs_clarification:
            raise ValueError("intent=needs_clarification requires needs_clarification=true.")

        if self.intent in (IntentType.GET_KPI, IntentType.BREAKDOWN_KPI):
            if not self.needs_clarification:
                if self.report_id is None:
                    raise ValueError("report_id is required for executable intents.")
                if self.filters is None:
                    raise ValueError("filters are required for executable intents.")
            if self.needs_clarification and self.report_id is None:
                raise ValueError("report_id is required when clarifying an executable intent.")

        if self.intent is IntentType.SMALL_TALK:
            if self.report_id is not None:
                raise ValueError("report_id must be null for small_talk.")
            if self.filters is not None:
                raise ValueError("filters must be null for small_talk.")
            if self.needs_clarification:
                raise ValueError("needs_clarification must be false for small_talk.")

        if self.intent is IntentType.UNSUPPORTED_REQUEST:
            if self.report_id is not None:
                raise ValueError("report_id must be null for unsupported requests.")
            if self.filters is not None:
                raise ValueError("filters must be null for unsupported requests.")
            if self.needs_clarification:
                raise ValueError(
                    "needs_clarification must be false for unsupported requests."
                )

        return self


class FilterMatchOutput(SchemaModel):
    matched_value: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning_notes: str | None = None


def build_interpret_request_messages(
    user_question: str,
    *,
    current_date: date | None = None,
) -> list[dict[str, str]]:
    if re.search(r"[\u0531-\u0556\u0561-\u0587]", user_question):
        language_name = "Armenian"
    elif re.search(r"[\u0400-\u04FF]", user_question):
        language_name = "Russian"
    else:
        language_name = "English"

    language_instruction = (
        "Language policy:\n"
        f'- The user question language is "{language_name}".\n'
        "- Keep JSON structure, enum values, report_id values, and filter keys "
        "exactly in English.\n"
        f'- Write only human-facing text fields ("clarification_question", "reasoning_notes") in '
        f'"{language_name}".'
    )

    date_instruction = ""
    if current_date is not None:
        date_instruction = (
            "\n\nTime policy:\n"
            f"- Current date is {current_date.isoformat()}.\n"
            "- Resolve relative periods (today, yesterday, this/last week, etc.) using this date."
        )

    return [
        {
            "role": "system",
            "content": (
                f"{INTERPRET_REQUEST_SYSTEM_PROMPT}\n\n"
                f"{language_instruction}"
                f"{date_instruction}"
            ),
        },
        {"role": "user", "content": user_question},
    ]


def build_small_talk_messages(user_question: str) -> list[dict[str, str]]:
    if re.search(r"[\u0531-\u0556\u0561-\u0587]", user_question):
        language_name = "Armenian"
    elif re.search(r"[\u0400-\u04FF]", user_question):
        language_name = "Russian"
    else:
        language_name = "English"

    return [
        {
            "role": "system",
            "content": (
                f"{SMALL_TALK_SYSTEM_PROMPT}\n\n"
                f'Reply language policy: prefer "{language_name}" for the final answer.'
            ),
        },
        {"role": "user", "content": user_question},
    ]


def build_filter_match_messages(
    *,
    user_question: str,
    filter_key: str,
    raw_value: str,
    candidates: list[str],
) -> list[dict[str, str]]:
    candidate_lines = "\n".join(f"- {candidate}" for candidate in candidates)
    user_content = (
        f"Question: {user_question}\n"
        f"Filter key: {filter_key}\n"
        f"Raw filter value: {raw_value}\n"
        "Candidates:\n"
        f"{candidate_lines}"
    )
    return [
        {"role": "system", "content": FILTER_MATCH_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def parse_interpretation_output_json(output_text: str) -> InterpretationOutput:
    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise InterpretationContractError("Model output is not valid JSON.") from exc

    return validate_interpretation_output(payload)


def validate_interpretation_output(payload: Mapping[str, Any] | Any) -> InterpretationOutput:
    if not isinstance(payload, Mapping):
        raise InterpretationContractError("Model output payload must be an object.")

    try:
        return InterpretationOutput.model_validate(payload)
    except ValidationError as exc:
        raise InterpretationContractError(
            "Model output failed interpretation schema validation."
        ) from exc


def parse_filter_match_output_json(
    output_text: str,
    *,
    candidates: list[str],
) -> FilterMatchOutput:
    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise FilterMatchContractError("Model output is not valid JSON.") from exc

    return validate_filter_match_output(payload, candidates=candidates)


def validate_filter_match_output(
    payload: Mapping[str, Any] | Any,
    *,
    candidates: list[str],
) -> FilterMatchOutput:
    if not isinstance(payload, Mapping):
        raise FilterMatchContractError("Model output payload must be an object.")

    try:
        output = FilterMatchOutput.model_validate(payload)
    except ValidationError as exc:
        raise FilterMatchContractError(
            "Model output failed filter-match schema validation."
        ) from exc

    if output.matched_value is not None and output.matched_value not in candidates:
        raise FilterMatchContractError("matched_value must be one of the provided candidates.")

    return output
