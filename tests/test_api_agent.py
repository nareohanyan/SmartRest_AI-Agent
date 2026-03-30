from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.agent.graph as graph_module
from app.api.app import create_app
from app.api.routes.agent import _get_runtime_service, _get_subscription_service
from app.api.schemas import AgentRunRequest
from app.core.auth import build_canonical_payload, sign_payload_token
from app.core.config import get_settings
from app.schemas.subscription import SubscriptionAccessDecision
from app.services.agent_runtime import AgentRuntimeExecutionError

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def app() -> FastAPI:
    return create_app()


def _missing_openai_key() -> Any:
    raise ValueError("OPENAI_API_KEY is not configured.")


@pytest.fixture(autouse=True)
def _disable_openai_client(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setattr(graph_module, "get_llm_client", _missing_openai_key)
    monkeypatch.setenv("SMARTREST_AUTH_SECRET_KEY", "test-secret")
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _allow_subscription_access(app: FastAPI) -> Iterator[None]:
    class _AllowingSubscriptionService:
        def evaluate_access(self, _verified_identity: Any) -> SubscriptionAccessDecision:
            return SubscriptionAccessDecision(
                allowed=True,
                reason_code="subscription_allowed",
                reason_message="AI agent subscription is active.",
            )

    async def _override_subscription_service() -> _AllowingSubscriptionService:
        return _AllowingSubscriptionService()

    app.dependency_overrides[_get_subscription_service] = _override_subscription_service
    try:
        yield
    finally:
        app.dependency_overrides.pop(_get_subscription_service, None)


def _auth_payload(
    *,
    profile_nick: str = "nick",
    user_id: int = 101,
    profile_id: int = 201,
    current_timestamp: int | None = None,
) -> dict[str, Any]:
    issued_at = current_timestamp if current_timestamp is not None else int(time.time())
    canonical_payload = build_canonical_payload(
        current_timestamp=issued_at,
        profile_nick=profile_nick,
        profile_id=profile_id,
        user_id=user_id,
    )
    return {
        "profile_nick": profile_nick,
        "user_id": user_id,
        "profile_id": profile_id,
        "current_timestamp": issued_at,
        "token": sign_payload_token("test-secret", canonical_payload),
    }


@pytest.fixture
async def api_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def _request_payload(
    question: str,
    *,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "chat_id": "11111111-1111-1111-1111-111111111111",
        "user_question": question,
        "auth": _auth_payload(),
        "scope_request": {
            "user_id": 101,
            "profile_id": 201,
            "profile_nick": "nick",
            "metadata": metadata or {},
        },
    }


async def test_supported_request_returns_completed_contract(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/agent/run",
        json=_request_payload("What were total sales 2026-03-01 to 2026-03-07?"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["chat_id"] == "11111111-1111-1111-1111-111111111111"
    assert isinstance(payload["run_id"], str) and payload["run_id"]
    assert payload["status"] == "completed"
    assert payload["answer"]
    assert payload["selected_report_id"] == "sales_total"
    assert payload["applied_filters"]["date_from"] == "2026-03-01"
    assert payload["applied_filters"]["date_to"] == "2026-03-07"
    assert "mock_backend_deterministic_data" in payload["warnings"]
    assert payload["needs_clarification"] is False
    assert payload["clarification_question"] is None


async def test_missing_date_returns_clarify_response(api_client: AsyncClient) -> None:
    response = await api_client.post("/agent/run", json=_request_payload("What were total sales?"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "clarify"
    assert payload["needs_clarification"] is True
    assert payload["clarification_question"]
    assert "date range" in payload["clarification_question"].lower()


async def test_smalltalk_returns_onboarding_contract(api_client: AsyncClient) -> None:
    response = await api_client.post("/agent/run", json=_request_payload("բարև"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "onboarding"
    assert payload["needs_clarification"] is False
    assert payload["clarification_question"] is None
    assert payload["answer"] == "Ողջու՜յն։ Ինչո՞վ կարող եմ օգնել ձեզ այսօր։"


async def test_smalltalk_in_russian_returns_onboarding_contract(api_client: AsyncClient) -> None:
    response = await api_client.post("/agent/run", json=_request_payload("здравствуйте"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "onboarding"
    assert payload["needs_clarification"] is False
    assert payload["clarification_question"] is None
    assert payload["answer"] == "Здравствуйте. Чем я могу вам сегодня помочь?"


async def test_casual_english_smalltalk_returns_onboarding_contract(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post("/agent/run", json=_request_payload("hello what's up"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "onboarding"
    assert payload["needs_clarification"] is False
    assert payload["clarification_question"] is None
    assert payload["answer"] == "Hello. Nice to see you here."


async def test_casual_armenian_smalltalk_returns_onboarding_contract(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post("/agent/run", json=_request_payload("ինչ կա"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "onboarding"
    assert payload["needs_clarification"] is False
    assert payload["clarification_question"] is None
    assert payload["answer"] == "Ողջու՜յն։ Ինչո՞վ կարող եմ օգնել ձեզ այսօր։"


async def test_typo_russian_greeting_returns_onboarding_contract(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post("/agent/run", json=_request_payload("здраствуйте"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "onboarding"
    assert payload["needs_clarification"] is False
    assert payload["clarification_question"] is None
    assert payload["answer"] == "Здравствуйте. Чем я могу вам сегодня помочь?"


async def test_unsupported_request_returns_rejected_status(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/agent/run",
        json=_request_payload("Show payroll tax trend 2026-03-01 to 2026-03-07."),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "rejected"
    assert payload["needs_clarification"] is False
    assert payload["selected_report_id"] is None


async def test_denied_scope_returns_denied_and_blocks_report_path(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post(
        "/agent/run",
        json=_request_payload(
            "What were total sales 2026-03-01 to 2026-03-07?",
            metadata={"access": "deny"},
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "denied"
    assert payload["selected_report_id"] is None
    assert payload["answer"] is not None


async def test_invalid_auth_token_returns_401(api_client: AsyncClient) -> None:
    payload = _request_payload("What were total sales 2026-03-01 to 2026-03-07?")
    payload["auth"]["token"] = "0" * 64

    response = await api_client.post("/agent/run", json=payload)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


async def test_mismatched_auth_and_scope_identity_returns_422(api_client: AsyncClient) -> None:
    payload = _request_payload("What were total sales 2026-03-01 to 2026-03-07?")
    payload["auth"]["profile_nick"] = "other"

    response = await api_client.post("/agent/run", json=payload)

    assert response.status_code == 422


async def test_inactive_subscription_returns_403(
    app: FastAPI,
    api_client: AsyncClient,
) -> None:
    class _DenyingSubscriptionService:
        def evaluate_access(self, _verified_identity: Any) -> SubscriptionAccessDecision:
            return SubscriptionAccessDecision(
                allowed=False,
                reason_code="subscription_expired",
                reason_message="AI agent subscription is inactive.",
            )

    async def _override_subscription_service() -> _DenyingSubscriptionService:
        return _DenyingSubscriptionService()

    app.dependency_overrides[_get_subscription_service] = _override_subscription_service
    try:
        response = await api_client.post(
            "/agent/run",
            json=_request_payload("What were total sales 2026-03-01 to 2026-03-07?"),
        )
    finally:
        app.dependency_overrides.pop(_get_subscription_service, None)

    assert response.status_code == 403
    assert response.json() == {"detail": "AI agent subscription is inactive."}


async def test_request_validation_error_returns_422(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/agent/run",
        json={
            "chat_id": "11111111-1111-1111-1111-111111111111",
            "user_question": "What were total sales?",
        },
    )

    assert response.status_code == 422


async def test_runtime_failure_returns_controlled_500(
    app: FastAPI,
    api_client: AsyncClient,
) -> None:
    class _FailingRuntime:
        def run(self, _request: AgentRunRequest, **_kwargs: Any) -> Any:
            raise AgentRuntimeExecutionError("boom")

    async def _override_dependency() -> _FailingRuntime:
        return _FailingRuntime()

    app.dependency_overrides[_get_runtime_service] = _override_dependency

    response = await api_client.post(
        "/agent/run",
        json=_request_payload("What were total sales 2026-03-01 to 2026-03-07?"),
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Agent runtime execution failed."}


async def test_health_endpoint_remains_available(api_client: AsyncClient) -> None:
    response = await api_client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
