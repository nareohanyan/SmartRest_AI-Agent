from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import Field, ValidationError

from app.schemas.analysis import AnalysisPlan, DimensionName, MetricName
from app.schemas.base import SchemaModel


def _enum_union_members(enum_type: type[MetricName] | type[DimensionName]) -> str:
    return " | ".join(f'"{member.value}"' for member in enum_type)


_SUPPORTED_METRIC_LIST = ", ".join(member.value for member in MetricName)
_SUPPORTED_DIMENSION_LIST = ", ".join(member.value for member in DimensionName)
_METRIC_ENUM_UNION = _enum_union_members(MetricName)
_DIMENSION_ENUM_UNION = _enum_union_members(DimensionName)


_PLAN_ANALYSIS_SYSTEM_PROMPT_TEMPLATE = """
You are SmartRest's planning engine.
Convert the user request into a strict analysis execution plan.

Return JSON only with this exact shape:
{
  "plan": {
    "intent": "metric_total" | "breakdown" | "trend" | "comparison" |
      "ranking" | "smalltalk" | "clarify" | "unsupported",
    "retrieval": {
      "mode": "total" | "breakdown" | "timeseries",
      "metric": <<METRIC_ENUM_UNION>>,
      "date_from": "YYYY-MM-DD",
      "date_to": "YYYY-MM-DD",
      "dimension": <<DIMENSION_ENUM_UNION>> | null
    } | null,
    "compare_to_previous_period": boolean,
    "previous_period_retrieval": {
      "mode": "total" | "breakdown" | "timeseries",
      "metric": <<METRIC_ENUM_UNION>>,
      "date_from": "YYYY-MM-DD",
      "date_to": "YYYY-MM-DD",
      "dimension": <<DIMENSION_ENUM_UNION>> | null
    } | null,
    "scalar_calculations": [],
    "include_moving_average": boolean,
    "moving_average_window": integer,
    "include_trend_slope": boolean,
    "ranking": {
      "mode": "top_k" | "bottom_k",
      "k": integer,
      "metric_key": string,
      "direction": "asc" | "desc" | null
    } | null,
    "needs_clarification": boolean,
    "clarification_question": string | null,
    "reasoning_notes": string | null
  },
  "confidence": number between 0 and 1
}

Rules:
- For greetings/smalltalk (for example hi, hello), output intent "smalltalk".
- If required dates are missing, output intent "clarify" and a clarification question.
- Never invent unknown metrics, dimensions, or retrieval modes.
- Supported metrics: <<SUPPORTED_METRIC_LIST>>.
- Supported dimensions: <<SUPPORTED_DIMENSION_LIST>>.
- Output JSON only, no markdown, no prose, no extra keys.
""".strip()

PLAN_ANALYSIS_SYSTEM_PROMPT = (
    _PLAN_ANALYSIS_SYSTEM_PROMPT_TEMPLATE.replace("<<METRIC_ENUM_UNION>>", _METRIC_ENUM_UNION)
    .replace("<<DIMENSION_ENUM_UNION>>", _DIMENSION_ENUM_UNION)
    .replace("<<SUPPORTED_METRIC_LIST>>", _SUPPORTED_METRIC_LIST)
    .replace("<<SUPPORTED_DIMENSION_LIST>>", _SUPPORTED_DIMENSION_LIST)
)


class PlanningContractError(ValueError):
    """Raised when model output violates planning schema contract."""


class LLMPlanEnvelope(SchemaModel):
    plan: AnalysisPlan
    confidence: float = Field(ge=0.0, le=1.0)


def build_plan_messages(user_question: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": PLAN_ANALYSIS_SYSTEM_PROMPT},
        {"role": "user", "content": user_question},
    ]


def parse_plan_output_json(output_text: str) -> LLMPlanEnvelope:
    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise PlanningContractError("Planner output is not valid JSON.") from exc

    return validate_plan_output(payload)


def validate_plan_output(payload: Mapping[str, Any] | Any) -> LLMPlanEnvelope:
    if not isinstance(payload, Mapping):
        raise PlanningContractError("Planner payload must be a JSON object.")

    try:
        return LLMPlanEnvelope.model_validate(payload)
    except ValidationError as exc:
        raise PlanningContractError("Planner output failed schema validation.") from exc
