from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.schemas import AgentRunRequest, AgentRunResponse
from app.services.agent_runtime import (
    AgentRuntimeExecutionError,
    AgentRuntimeService,
    get_agent_runtime_service,
)

router = APIRouter(prefix="/agent", tags=["agent"])


async def _get_runtime_service() -> AgentRuntimeService:
    return get_agent_runtime_service()


@router.post("/run", response_model=AgentRunResponse)
async def run_agent(
    payload: AgentRunRequest,
    runtime_service: AgentRuntimeService = Depends(_get_runtime_service),
) -> AgentRunResponse:
    try:
        return runtime_service.run(payload)
    except AgentRuntimeExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent runtime execution failed.",
        ) from exc
