from __future__ import annotations

import pytest

from app.agent.llm.exceptions import LLMClientError
from app.api.schemas import AgentRunRequest
from app.schemas.agent import LLMErrorCategory
from app.services.agent_runtime import (
    AgentRuntimeExecutionError,
    AgentRuntimeService,
    RuntimeErrorCategory,
)


class _RaisingGraph:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def invoke(self, _state: dict[str, object]) -> dict[str, object]:
        raise self._exc


def _request_payload() -> AgentRunRequest:
    return AgentRunRequest.model_validate(
        {
            "thread_id": "thread-1",
            "user_question": "What were total sales 2026-03-01 to 2026-03-07?",
            "scope_request": {
                "user_id": "u-1",
                "profile_id": "p-1",
                "profile_nick": "nick",
                "metadata": {},
            },
        }
    )


@pytest.mark.parametrize(
    ("llm_category", "runtime_category"),
    [
        (LLMErrorCategory.TIMEOUT, RuntimeErrorCategory.LLM_TIMEOUT),
        (LLMErrorCategory.CONNECTION, RuntimeErrorCategory.LLM_CONNECTION),
        (LLMErrorCategory.RATE_LIMIT, RuntimeErrorCategory.LLM_RATE_LIMIT),
        (LLMErrorCategory.AUTHENTICATION, RuntimeErrorCategory.LLM_AUTHENTICATION),
        (LLMErrorCategory.BAD_REQUEST, RuntimeErrorCategory.LLM_BAD_REQUEST),
        (LLMErrorCategory.SERVER, RuntimeErrorCategory.LLM_SERVER),
        (LLMErrorCategory.UNKNOWN, RuntimeErrorCategory.LLM_UNKNOWN),
    ],
)
def test_runtime_maps_llm_failure_to_controlled_categories(
    llm_category: LLMErrorCategory,
    runtime_category: RuntimeErrorCategory,
) -> None:
    llm_error = LLMClientError("llm failed", category=llm_category, retryable=False)
    runtime_service = AgentRuntimeService(graph_factory=lambda: _RaisingGraph(llm_error))

    with pytest.raises(AgentRuntimeExecutionError) as exc_info:
        runtime_service.run(_request_payload())

    assert exc_info.value.category is runtime_category


def test_runtime_maps_non_llm_exception_to_internal_category() -> None:
    runtime_service = AgentRuntimeService(graph_factory=lambda: _RaisingGraph(RuntimeError("boom")))

    with pytest.raises(AgentRuntimeExecutionError) as exc_info:
        runtime_service.run(_request_payload())

    assert exc_info.value.category is RuntimeErrorCategory.INTERNAL
