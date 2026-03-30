from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Any
from uuid import uuid4

from app.agent.graph import build_agent_graph
from app.agent.llm.exceptions import LLMClientError
from app.api.schemas import AgentRunRequest, AgentRunResponse
from app.core.auth import VerifiedIdentity
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
        graph_factory: Callable[[], Any] = build_agent_graph,
        persistence_service: RuntimePersistenceService | None = None,
    ) -> None:
        self._graph_factory = graph_factory
        self._persistence_service = persistence_service or get_runtime_persistence_service()

    def run(
        self,
        request: AgentRunRequest,
        *,
        verified_identity: VerifiedIdentity,
    ) -> AgentRunResponse:
        start_persistence_result = self._persistence_service.start_run(
            chat_id=request.chat_id,
            user_id=verified_identity.user_id,
            profile_id=verified_identity.profile_id,
            profile_nick=verified_identity.profile_nick,
            intent=None,
            metadata_json={"chat_id": str(request.chat_id)},
        )
        start_warnings = start_persistence_result.warnings
        run_id = start_persistence_result.internal_run_id or uuid4()
        initial_state = AgentState(
            chat_id=request.chat_id,
            run_id=run_id,
            user_question=request.user_question,
            scope_request=ResolveScopeRequest.model_validate(
                {
                    "user_id": verified_identity.user_id,
                    "profile_id": verified_identity.profile_id,
                    "profile_nick": verified_identity.profile_nick,
                    "metadata": request.scope_request.metadata,
                    "requested_branch_ids": request.scope_request.requested_branch_ids,
                    "requested_export_mode": request.scope_request.requested_export_mode,
                }
            ),
            needs_clarification=False,
            status=RunStatus.RUNNING,
        )

        try:
            graph = self._graph_factory()
            runtime_output = graph.invoke(initial_state.model_dump(mode="json"))
            final_state = AgentState.model_validate(runtime_output)
        except LLMClientError as exc:
            self._persistence_service.finish_run(
                chat_id=start_persistence_result.chat_id,
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
                chat_id=start_persistence_result.chat_id,
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

        finish_persistence_result = self._persistence_service.finish_run(
            chat_id=start_persistence_result.chat_id,
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

        return AgentRunResponse(
            chat_id=final_state.chat_id,
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


def get_agent_runtime_service() -> AgentRuntimeService:
    return AgentRuntimeService()
