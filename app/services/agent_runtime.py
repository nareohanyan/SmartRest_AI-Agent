from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Any
from uuid import uuid4

from app.agent.graph import build_agent_graph
from app.agent.llm.exceptions import LLMClientError
from app.api.schemas import AgentRunRequest, AgentRunResponse, PlatformAdminRunRequest
from app.core.auth import VerifiedIdentity, VerifiedPlatformAdmin
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
        scope_request = ResolveScopeRequest.model_validate(
            {
                "user_id": verified_identity.user_id,
                "profile_id": verified_identity.profile_id,
                "profile_nick": verified_identity.profile_nick,
                "metadata": request.scope_request.metadata,
                "requested_branch_ids": request.scope_request.requested_branch_ids,
                "requested_export_mode": request.scope_request.requested_export_mode,
            }
        )
        return self._run_internal(
            chat_id=request.chat_id,
            user_question=request.user_question,
            scope_request=scope_request,
            persistence_identity=verified_identity,
            metadata_json={
                "chat_id": str(request.chat_id),
                "actor_type": "tenant_user",
            },
        )

    def run_as_platform_admin(
        self,
        request: PlatformAdminRunRequest,
        *,
        target_identity: VerifiedIdentity,
        verified_admin: VerifiedPlatformAdmin,
    ) -> AgentRunResponse:
        scope_request = ResolveScopeRequest.model_validate(
            {
                "user_id": target_identity.user_id,
                "profile_id": target_identity.profile_id,
                "profile_nick": target_identity.profile_nick,
                "metadata": request.metadata,
                "requested_branch_ids": request.requested_branch_ids,
                "requested_export_mode": request.requested_export_mode,
            }
        )
        return self._run_internal(
            chat_id=request.chat_id,
            user_question=request.user_question,
            scope_request=scope_request,
            persistence_identity=target_identity,
            metadata_json={
                "chat_id": str(request.chat_id),
                "actor_type": "platform_admin",
                "admin_id": verified_admin.admin_id,
                "target_profile_id": target_identity.profile_id,
                "target_user_id": target_identity.user_id,
            },
        )

    def _run_internal(
        self,
        *,
        chat_id: Any,
        user_question: str,
        scope_request: ResolveScopeRequest,
        persistence_identity: VerifiedIdentity,
        metadata_json: dict[str, Any],
    ) -> AgentRunResponse:
        start_persistence_result = self._persistence_service.start_run(
            chat_id=chat_id,
            user_id=persistence_identity.user_id,
            profile_id=persistence_identity.profile_id,
            profile_nick=persistence_identity.profile_nick,
            intent=None,
            metadata_json=metadata_json,
        )
        start_warnings = start_persistence_result.warnings
        run_id = start_persistence_result.internal_run_id or uuid4()
        initial_state = AgentState(
            chat_id=chat_id,
            run_id=run_id,
            user_question=user_question,
            scope_request=scope_request,
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
                question=user_question,
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
                question=user_question,
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
