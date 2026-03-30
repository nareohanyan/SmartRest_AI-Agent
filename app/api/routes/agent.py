from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.schemas import AgentRunRequest, AgentRunResponse
from app.core.auth import verify_signed_payload
from app.services.agent_runtime import (
    AgentRuntimeExecutionError,
    AgentRuntimeService,
    get_agent_runtime_service,
)
from app.services.subscription_access import (
    SubscriptionAccessService,
    SubscriptionAccessServiceError,
    get_subscription_access_service,
)

router = APIRouter(prefix="/agent", tags=["agent"])


async def _get_runtime_service() -> AgentRuntimeService:
    return get_agent_runtime_service()


async def _get_subscription_service() -> SubscriptionAccessService:
    return get_subscription_access_service()


@router.post("/run", response_model=AgentRunResponse)
async def run_agent(
    request: Request,
    payload: AgentRunRequest,
    runtime_service: AgentRuntimeService = Depends(_get_runtime_service),
    subscription_service: SubscriptionAccessService = Depends(_get_subscription_service),
) -> AgentRunResponse:
    request_id = request.headers.get("x-request-id", str(uuid4()))
    verified_identity = verify_signed_payload(
        profile_nick=payload.auth.profile_nick,
        user_id=payload.auth.user_id,
        profile_id=payload.auth.profile_id,
        current_timestamp=payload.auth.current_timestamp,
        token=payload.auth.token,
        request_id=request_id,
    )
    try:
        access_decision = subscription_service.evaluate_access(verified_identity)
    except SubscriptionAccessServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Subscription access check failed.",
        ) from exc

    if not access_decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=access_decision.reason_message,
        )
    try:
        return runtime_service.run(payload, verified_identity=verified_identity)
    except AgentRuntimeExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent runtime execution failed.",
        ) from exc
