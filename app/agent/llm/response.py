from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import Field

from app.schemas.base import SchemaModel

RESPONSE_COMPOSER_SYSTEM_PROMPT = """
You are SmartRest's response writer.
Write one concise, natural-language answer for the user from the provided JSON context.

Rules:
- Respect `language_hint` ("hy" for Armenian, "en" for English).
- Use only facts present in context.
- Never invent metrics, dates, numbers, policies, or scope facts.
- Keep tone natural and human, but concise.
- For route="smalltalk", greet briefly and ask one concrete analytics follow-up question.
- For route="smalltalk", do not list capabilities unless explicitly needed by user context.
- For route="clarify", ask only for required missing details.
- For route in {"safe_answer", "reject"}, politely explain boundary and supported areas.
- For route="completed", summarize provided result facts naturally.
- Output plain text only. No JSON, no markdown, no code fences.
""".strip()


class ResponseRenderContext(SchemaModel):
    route: str
    language_hint: str
    user_question: str
    factual_answer: str
    policy_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)


def build_response_messages(
    context: Mapping[str, Any] | ResponseRenderContext,
) -> list[dict[str, str]]:
    payload: dict[str, Any]
    if isinstance(context, ResponseRenderContext):
        payload = context.model_dump(mode="json")
    else:
        payload = ResponseRenderContext.model_validate(context).model_dump(mode="json")

    return [
        {"role": "system", "content": RESPONSE_COMPOSER_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
