from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from app.agent.graph import build_agent_graph
from app.api.schemas import AgentRunRequest, AgentRunResponse
from app.schemas.agent import AgentState, RunStatus
from app.schemas.tools import ResolveScopeRequest


class AgentRuntimeExecutionError(RuntimeError):
    pass

class AgentRuntimeService:
    def __init__(self, graph_factory: Callable[[], Any] = build_agent_graph) -> None:
        self._graph_factory = graph_factory

    def run(self, request: AgentRunRequest) -> AgentRunResponse:
        run_id = uuid4().hex
        initial_state = AgentState(
            thread_id=request.thread_id,
            run_id=run_id,
            user_question=request.user_question,
            scope_request=ResolveScopeRequest.model_validate(request.scope_request.model_dump()),
            needs_clarification=False,
            status=RunStatus.RUNNING,
        )

        try:
            graph = self._graph_factory()
            runtime_output = graph.invoke(initial_state.model_dump(mode="json"))
            final_state = AgentState.model_validate(runtime_output)
        except Exception as exc:
            raise AgentRuntimeExecutionError("Agent runtime execution failed.") from exc

        return AgentRunResponse(
            thread_id=final_state.thread_id,
            run_id=final_state.run_id,
            status=final_state.status,
            answer=final_state.final_answer,
            selected_report_id=final_state.selected_report_id,
            applied_filters=final_state.filters,
            warnings=final_state.warnings,
            needs_clarification=final_state.needs_clarification,
            clarification_question=final_state.clarification_question,
        )


def get_agent_runtime_service() -> AgentRuntimeService:
    return AgentRuntimeService()
