from __future__ import annotations

import inspect
from collections.abc import Callable
from enum import Enum
from typing import Any
from uuid import uuid4

from app.agent.graph import build_agent_graph
from app.agent.llm.exceptions import LLMClientError
from app.api.schemas import AgentRunRequest, AgentRunResponse
from app.persistence.runtime_persistence import (
    RuntimePersistenceService,
    get_runtime_persistence_service,
)
from app.schemas.agent import AgentState, LLMErrorCategory, RunStatus
from app.schemas.tools import ResolveScopeRequest


class RuntimeErrorCategory(str, Enum):
    INTERNAL = "internal"
    LLM_TIMEOUT = "llm_timeout"
    LLM_CONNECTION = "llm_connection"
    LLM_RATE_LIMIT = "llm_rate_limit"
    LLM_AUTHENTICATION = "llm_authentication"
    LLM_BAD_REQUEST = "llm_bad_request"
    LLM_SERVER = "llm_server"
    LLM_UNKNOWN = "llm_unknown"


class AgentRuntimeExecutionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        category: RuntimeErrorCategory = RuntimeErrorCategory.INTERNAL,
    ) -> None:
        super().__init__(message)
        self.category = category


class AgentRuntimeService:
    def __init__(
        self,
        graph_factory: Callable[..., Any] = build_agent_graph,
        persistence_service: RuntimePersistenceService | None = None,
    ) -> None:
        self._graph_factory = graph_factory
        self._persistence_service = persistence_service or get_runtime_persistence_service()

    def run(self, request: AgentRunRequest) -> AgentRunResponse:
        run_id = uuid4()
        initial_state = AgentState(
            thread_id=request.thread_id,
            run_id=run_id,
            user_question=request.user_question,
            scope_request=ResolveScopeRequest.model_validate(request.scope_request.model_dump()),
            needs_clarification=False,
            status=RunStatus.RUNNING,
        )

        start_persistence_result = self._persistence_service.start_run(
            thread_id=request.thread_id,
            user_id=request.scope_request.user_id,
            profile_id=request.scope_request.profile_id,
            profile_nick=request.scope_request.profile_nick,
            intent=None,
            metadata_json={"thread_id": str(request.thread_id)},
        )
        start_warnings = start_persistence_result.warnings

        initial_state = AgentState(
            thread_id=request.thread_id,
            run_id=run_id,
            user_question=request.user_question,
            scope_request=ResolveScopeRequest.model_validate(request.scope_request.model_dump()),
            needs_clarification=False,
            internal_thread_id=start_persistence_result.thread_id,
            internal_run_id=start_persistence_result.internal_run_id,
            status=RunStatus.RUNNING,
        )

        try:
            graph = _build_graph(
                self._graph_factory,
                persistence_service=self._persistence_service,
            )
            runtime_output = graph.invoke(initial_state.model_dump(mode="json"))
            final_state = AgentState.model_validate(runtime_output)
        except LLMClientError as exc:
            self._persistence_service.finish_run(
                thread_id=start_persistence_result.thread_id,
                internal_run_id=start_persistence_result.internal_run_id,
                status=RunStatus.FAILED,
                question=request.user_question,
                answer=None,
                error_message=str(exc),
                error_code=f"llm_{exc.category.value}",
            )
            raise AgentRuntimeExecutionError(
                "Agent runtime execution failed.",
                category=_map_llm_error_category(exc.category),
            ) from exc
        except Exception as exc:
            self._persistence_service.finish_run(
                thread_id=start_persistence_result.thread_id,
                internal_run_id=start_persistence_result.internal_run_id,
                status=RunStatus.FAILED,
                question=request.user_question,
                answer=None,
                error_message=str(exc),
                error_code="runtime_internal_error",
            )
            raise AgentRuntimeExecutionError(
                "Agent runtime execution failed.",
                category=RuntimeErrorCategory.INTERNAL,
            ) from exc

        if not final_state.run_persisted:
            finish_persistence_result = self._persistence_service.finish_run(
                thread_id=start_persistence_result.thread_id,
                internal_run_id=start_persistence_result.internal_run_id,
                status=final_state.status,
                question=final_state.user_question,
                answer=final_state.final_answer,
                error_message=(
                    final_state.final_answer
                    if final_state.status is RunStatus.FAILED
                    else None
                ),
            )
            warnings = _merge_warnings(
                final_state.warnings,
                start_warnings,
                finish_persistence_result.warnings,
            )
        else:
            warnings = _merge_warnings(final_state.warnings, start_warnings)

        return AgentRunResponse(
            thread_id=final_state.thread_id,
            run_id=final_state.run_id,
            status=final_state.status,
            answer=final_state.final_answer,
            selected_report_id=final_state.selected_report_id,
            applied_filters=final_state.filters,
            warnings=warnings,
            needs_clarification=final_state.needs_clarification,
            clarification_question=final_state.clarification_question,
        )


def _map_llm_error_category(category: LLMErrorCategory) -> RuntimeErrorCategory:
    mapping: dict[LLMErrorCategory, RuntimeErrorCategory] = {
        LLMErrorCategory.TIMEOUT: RuntimeErrorCategory.LLM_TIMEOUT,
        LLMErrorCategory.CONNECTION: RuntimeErrorCategory.LLM_CONNECTION,
        LLMErrorCategory.RATE_LIMIT: RuntimeErrorCategory.LLM_RATE_LIMIT,
        LLMErrorCategory.AUTHENTICATION: RuntimeErrorCategory.LLM_AUTHENTICATION,
        LLMErrorCategory.BAD_REQUEST: RuntimeErrorCategory.LLM_BAD_REQUEST,
        LLMErrorCategory.SERVER: RuntimeErrorCategory.LLM_SERVER,
        LLMErrorCategory.UNKNOWN: RuntimeErrorCategory.LLM_UNKNOWN,
    }
    return mapping[category]


def _merge_warnings(*warning_groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for warning_group in warning_groups:
        for warning in warning_group:
            if warning in seen:
                continue
            seen.add(warning)
            merged.append(warning)
    return merged


def _build_graph(
    graph_factory: Callable[..., Any],
    *,
    persistence_service: RuntimePersistenceService,
) -> Any:
    try:
        parameters = inspect.signature(graph_factory).parameters
    except (TypeError, ValueError):
        return graph_factory()
    if "persistence_service" in parameters:
        return graph_factory(persistence_service=persistence_service)
    if len(parameters) == 1:
        return graph_factory(persistence_service)
    return graph_factory()


def get_agent_runtime_service() -> AgentRuntimeService:
    return AgentRuntimeService()
