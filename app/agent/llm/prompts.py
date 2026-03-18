from __future__ import annotations

import json
from collections.abc import Mapping
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

Return only one valid JSON object with this exact shape:
{
  "intent": "get_kpi" | "breakdown_kpi" | "needs_clarification" | "unsupported_request",
  "report_id": "sales_total" | "order_count" | "average_check" | "sales_by_source" | null,
  "filters": {"date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD", "source": "..."} | null,
  "needs_clarification": boolean,
  "clarification_question": string | null,
  "confidence": number between 0 and 1,
  "reasoning_notes": string | null
}

Interpretation policy:
- Use "unsupported_request" only when the business question is outside supported reports.
- Use "needs_clarification" when required filters are missing or ambiguous.
- For executable intents ("get_kpi", "breakdown_kpi"), include both report_id and full filters.
- If the question implies "by source" breakdown, use report_id "sales_by_source" and intent
  "breakdown_kpi".
- Use "source" filter only for report_id "sales_by_source".
- If date range is not explicit as YYYY-MM-DD to YYYY-MM-DD, ask clarification.
- Never invent unsupported metrics, report IDs, or filter keys.

Confidence policy:
- >= 0.85 only when report_id and required filters are explicit and unambiguous.
- 0.50-0.84 when interpretation is plausible but missing required details.
- < 0.50 when request is unsupported or highly ambiguous.

Output rules:
- Output JSON only, no markdown, no prose, no code fences.
- Do not include extra keys.
""".strip()

CLARIFICATION_FALLBACK_QUESTION = (
    "Please clarify your request with report type and date range (YYYY-MM-DD to YYYY-MM-DD)."
)


class InterpretationContractError(ValueError):
    """Raised when model output violates the interpretation schema contract."""


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


def build_interpret_request_messages(user_question: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": INTERPRET_REQUEST_SYSTEM_PROMPT},
        {"role": "user", "content": user_question},
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
