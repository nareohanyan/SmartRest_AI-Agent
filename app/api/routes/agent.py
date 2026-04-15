from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.schemas import (
    AgentRunRequest,
    AgentRunResponse,
    PlatformAdminProfilesRequest,
    PlatformAdminProfilesResponse,
    PlatformAdminProfileSummary,
    PlatformAdminRunRequest,
)
from app.core.auth import verify_platform_admin_payload, verify_signed_payload
from app.core.config import get_settings
from app.services.agent_runtime import (
    AgentRuntimeExecutionError,
    AgentRuntimeService,
    get_agent_runtime_service,
)
from app.services.platform_admin import (
    PlatformAdminService,
    PlatformAdminServiceError,
    PlatformAdminTargetNotFoundError,
    PlatformAdminTargetValidationError,
    get_platform_admin_service,
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


async def _get_platform_admin_dependency() -> PlatformAdminService:
    return get_platform_admin_service()


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


@router.post("/admin/profiles", response_model=PlatformAdminProfilesResponse)
async def list_admin_profiles(
    request: Request,
    payload: PlatformAdminProfilesRequest,
    admin_service: PlatformAdminService = Depends(_get_platform_admin_dependency),
) -> PlatformAdminProfilesResponse:
    request_id = request.headers.get("x-request-id", str(uuid4()))
    verify_platform_admin_payload(
        admin_id=payload.admin_auth.admin_id,
        current_timestamp=payload.admin_auth.current_timestamp,
        token=payload.admin_auth.token,
        request_id=request_id,
    )
    try:
        profiles = admin_service.list_profiles()
    except PlatformAdminServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Platform admin profile lookup failed.",
        ) from exc
    return PlatformAdminProfilesResponse(
        profiles=[
            PlatformAdminProfileSummary(
                profile_id=profile.profile_id,
                name=profile.name,
                profile_nick=profile.profile_nick,
                subscription_status=profile.subscription_status,
                subscription_expires_at=(
                    profile.subscription_expires_at.isoformat()
                    if profile.subscription_expires_at is not None
                    else None
                ),
                default_user_id=profile.default_user_id,
                user_count=profile.user_count,
            )
            for profile in profiles
        ]
    )


@router.post("/admin/run", response_model=AgentRunResponse)
async def run_agent_as_platform_admin(
    request: Request,
    payload: PlatformAdminRunRequest,
    runtime_service: AgentRuntimeService = Depends(_get_runtime_service),
    subscription_service: SubscriptionAccessService = Depends(_get_subscription_service),
    admin_service: PlatformAdminService = Depends(_get_platform_admin_dependency),
) -> AgentRunResponse:
    request_id = request.headers.get("x-request-id", str(uuid4()))
    verified_admin = verify_platform_admin_payload(
        admin_id=payload.admin_auth.admin_id,
        current_timestamp=payload.admin_auth.current_timestamp,
        token=payload.admin_auth.token,
        request_id=request_id,
    )
    try:
        target_identity = admin_service.resolve_target(
            target_profile_id=payload.target_profile_id,
            target_profile_nick=payload.target_profile_nick,
            target_user_id=payload.target_user_id,
        )
    except PlatformAdminTargetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PlatformAdminTargetValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except PlatformAdminServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Platform admin target resolution failed.",
        ) from exc

    settings = get_settings()
    bypass_subscription = settings.platform_admin_bypass_subscription
    if not bypass_subscription:
        try:
            access_decision = subscription_service.evaluate_access(target_identity)
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
        response = runtime_service.run_as_platform_admin(
            payload,
            target_identity=target_identity,
            verified_admin=verified_admin,
        )
    except AgentRuntimeExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent runtime execution failed.",
        ) from exc

    warnings = list(response.warnings)
    if "platform_admin_mode" not in warnings:
        warnings.append("platform_admin_mode")
    if bypass_subscription and "platform_admin_subscription_bypass" not in warnings:
        warnings.append("platform_admin_subscription_bypass")
    return response.model_copy(update={"warnings": warnings})
