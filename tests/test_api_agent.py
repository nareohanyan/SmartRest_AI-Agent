from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.schemas import AgentRunRequest
from app.services.agent_runtime import AgentRuntimeExecutionError, get_agent_runtime_service


def _request_payload(
    question: str,
    *,
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "thread_id": "thread-api-1",
        "user_question": question,
        "scope_request": {
            "user_id": "u-1",
            "profile_id": "p-1",
            "profile_nick": "nick",
            "metadata": metadata or {},
        },
    }


def test_supported_request_returns_completed_contract() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/agent/run",
        json=_request_payload("What were total sales 2026-03-01 to 2026-03-07?"),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["thread_id"] == "thread-api-1"
    assert isinstance(payload["run_id"], str) and payload["run_id"]
    assert payload["status"] == "completed"
    assert payload["answer"]
    assert payload["selected_report_id"] == "sales_total"
    assert payload["applied_filters"]["date_from"] == "2026-03-01"
    assert payload["applied_filters"]["date_to"] == "2026-03-07"
    assert payload["warnings"] == ["mock_backend_deterministic_data"]
    assert payload["needs_clarification"] is False
    assert payload["clarification_question"] is None


def test_missing_date_returns_clarify_response() -> None:
    client = TestClient(create_app())
    response = client.post("/agent/run", json=_request_payload("What were total sales?"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "clarify"
    assert payload["needs_clarification"] is True
    assert payload["clarification_question"]
    assert "date range" in payload["clarification_question"].lower()


def test_unsupported_request_returns_rejected_status() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/agent/run",
        json=_request_payload("Show payroll tax trend 2026-03-01 to 2026-03-07."),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "rejected"
    assert payload["needs_clarification"] is False
    assert payload["selected_report_id"] is None


def test_denied_scope_returns_denied_and_blocks_report_path() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/agent/run",
        json=_request_payload(
            "What were total sales 2026-03-01 to 2026-03-07?",
            metadata={"access": "deny"},
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "denied"
    assert payload["selected_report_id"] is not None
    assert payload["answer"] is not None


def test_request_validation_error_returns_422() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/agent/run",
        json={
            "thread_id": "thread-api-1",
            "user_question": "What were total sales?",
        },
    )

    assert response.status_code == 422


def test_runtime_failure_returns_controlled_500() -> None:
    app = create_app()

    class _FailingRuntime:
        def run(self, _request: AgentRunRequest) -> Any:
            raise AgentRuntimeExecutionError("boom")

    def _override_dependency() -> _FailingRuntime:
        return _FailingRuntime()

    app.dependency_overrides[get_agent_runtime_service] = _override_dependency
    client = TestClient(app)

    response = client.post(
        "/agent/run",
        json=_request_payload("What were total sales 2026-03-01 to 2026-03-07?"),
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Agent runtime execution failed."}


def test_health_endpoint_remains_available() -> None:
    client = TestClient(create_app())
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
