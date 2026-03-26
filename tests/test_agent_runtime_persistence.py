from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.agent.llm.exceptions import LLMClientError
from app.api.schemas import AgentRunRequest
from app.persistence.runtime_persistence import (
    FinishRunPersistenceResult,
    StartRunPersistenceResult,
)
from app.schemas.agent import LLMErrorCategory, RunStatus
from app.services.agent_runtime import AgentRuntimeExecutionError, AgentRuntimeService


def _request_payload() -> AgentRunRequest:
    return AgentRunRequest.model_validate(
        {
            "chat_id": "11111111-1111-1111-1111-111111111111",
            "user_question": "What were total sales 2026-03-01 to 2026-03-07?",
            "scope_request": {
                "user_id": 101,
                "profile_id": 201,
                "profile_nick": "nick",
                "metadata": {},
            },
        }
    )


class _SuccessGraph:
    def invoke(self, state: dict[str, object]) -> dict[str, object]:
        output = dict(state)
        output.update(
            {
                "status": "completed",
                "intent": "get_kpi",
                "selected_report_id": "sales_total",
                "filters": {"date_from": "2026-03-01", "date_to": "2026-03-07"},
                "needs_clarification": False,
                "clarification_question": None,
                "warnings": ["runtime_warning"],
                "final_answer": "Report answer",
            }
        )
        return output


class _TerminalGraph:
    def __init__(self, status: RunStatus) -> None:
        self._status = status

    def invoke(self, state: dict[str, object]) -> dict[str, object]:
        output = dict(state)
        output.update(
            {
                "status": self._status.value,
                "intent": "get_kpi",
                "selected_report_id": "sales_total",
                "filters": {"date_from": "2026-03-01", "date_to": "2026-03-07"},
                "warnings": [],
                "final_answer": f"terminal:{self._status.value}",
            }
        )
        if self._status is RunStatus.CLARIFY:
            output["needs_clarification"] = True
            output["clarification_question"] = "Please provide a date range."
        else:
            output["needs_clarification"] = False
            output["clarification_question"] = None
        return output


class _RaisingGraph:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def invoke(self, _state: dict[str, object]) -> dict[str, object]:
        raise self._exc


@dataclass
class _PersistenceSpy:
    start_result: StartRunPersistenceResult
    finish_result: FinishRunPersistenceResult
    start_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_calls: list[dict[str, Any]] = field(default_factory=list)

    def start_run(self, **kwargs: Any) -> StartRunPersistenceResult:
        self.start_calls.append(kwargs)
        return self.start_result

    def finish_run(self, **kwargs: Any) -> FinishRunPersistenceResult:
        self.finish_calls.append(kwargs)
        return self.finish_result


def test_runtime_merges_persistence_warnings_into_response() -> None:
    internal_run_id = uuid4()
    spy = _PersistenceSpy(
        start_result=StartRunPersistenceResult(
            chat_id=uuid4(),
            internal_run_id=internal_run_id,
            warnings=["persistence_warning_start"],
        ),
        finish_result=FinishRunPersistenceResult(
            warnings=["persistence_warning_finish", "persistence_warning_start"],
        ),
    )
    runtime_service = AgentRuntimeService(
        graph_factory=lambda: _SuccessGraph(),
        persistence_service=spy,  # type: ignore[arg-type]
    )

    response = runtime_service.run(_request_payload())

    assert response.status is RunStatus.COMPLETED
    assert response.run_id == internal_run_id
    assert response.warnings == [
        "runtime_warning",
        "persistence_warning_start",
        "persistence_warning_finish",
    ]
    assert len(spy.start_calls) == 1
    assert len(spy.finish_calls) == 1


@pytest.mark.parametrize(
    "terminal_status",
    [
        RunStatus.COMPLETED,
        RunStatus.ONBOARDING,
        RunStatus.CLARIFY,
        RunStatus.REJECTED,
        RunStatus.DENIED,
        RunStatus.FAILED,
    ],
)
def test_runtime_persists_finish_for_each_terminal_graph_status(
    terminal_status: RunStatus,
) -> None:
    spy = _PersistenceSpy(
        start_result=StartRunPersistenceResult(
            chat_id=uuid4(),
            internal_run_id=uuid4(),
        ),
        finish_result=FinishRunPersistenceResult(),
    )
    runtime_service = AgentRuntimeService(
        graph_factory=lambda: _TerminalGraph(terminal_status),
        persistence_service=spy,  # type: ignore[arg-type]
    )

    response = runtime_service.run(_request_payload())

    assert response.status is terminal_status
    assert len(spy.finish_calls) == 1
    assert spy.finish_calls[0]["status"] is terminal_status
    if terminal_status is RunStatus.FAILED:
        assert spy.finish_calls[0]["error_message"] == "terminal:failed"
    else:
        assert spy.finish_calls[0]["error_message"] is None


def test_runtime_persists_failed_terminal_status_on_llm_error() -> None:
    spy = _PersistenceSpy(
        start_result=StartRunPersistenceResult(
            chat_id=uuid4(),
            internal_run_id=uuid4(),
        ),
        finish_result=FinishRunPersistenceResult(),
    )
    runtime_service = AgentRuntimeService(
        graph_factory=lambda: _RaisingGraph(
            LLMClientError("llm failure", category=LLMErrorCategory.TIMEOUT, retryable=False)
        ),
        persistence_service=spy,  # type: ignore[arg-type]
    )

    with pytest.raises(AgentRuntimeExecutionError):
        runtime_service.run(_request_payload())

    assert len(spy.finish_calls) == 1
    assert spy.finish_calls[0]["status"] is RunStatus.FAILED
    assert spy.finish_calls[0]["error_code"] == "llm_timeout"


def test_runtime_persists_failed_terminal_status_on_internal_error() -> None:
    spy = _PersistenceSpy(
        start_result=StartRunPersistenceResult(
            chat_id=uuid4(),
            internal_run_id=uuid4(),
        ),
        finish_result=FinishRunPersistenceResult(),
    )
    runtime_service = AgentRuntimeService(
        graph_factory=lambda: _RaisingGraph(RuntimeError("boom")),
        persistence_service=spy,  # type: ignore[arg-type]
    )

    with pytest.raises(AgentRuntimeExecutionError):
        runtime_service.run(_request_payload())

    assert len(spy.finish_calls) == 1
    assert spy.finish_calls[0]["status"] is RunStatus.FAILED
    assert spy.finish_calls[0]["error_code"] == "runtime_internal_error"


def test_runtime_uses_fallback_run_id_when_persistence_run_id_missing() -> None:
    spy = _PersistenceSpy(
        start_result=StartRunPersistenceResult(
            chat_id=None,
            internal_run_id=None,
            warnings=["persistence_warning_start"],
        ),
        finish_result=FinishRunPersistenceResult(
            warnings=["persistence_warning_finish"],
        ),
    )
    runtime_service = AgentRuntimeService(
        graph_factory=lambda: _SuccessGraph(),
        persistence_service=spy,  # type: ignore[arg-type]
    )

    response = runtime_service.run(_request_payload())

    assert response.status is RunStatus.COMPLETED
    assert isinstance(response.run_id, UUID)
    assert response.warnings == [
        "runtime_warning",
        "persistence_warning_start",
        "persistence_warning_finish",
    ]
