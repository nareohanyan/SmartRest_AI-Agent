"""End-to-end tests for the minimal Task 9 LangGraph workflow."""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import pytest

import app.agent.graph as graph_module
from app.agent.graph import build_agent_graph
from app.agent.llm.exceptions import LLMClientError
from app.schemas.agent import AgentState, LLMErrorCategory, RunStatus
from app.schemas.reports import ReportType


class _FakeLLMClient:
    def __init__(self, *, output_text: str | None = None, exc: Exception | None = None) -> None:
        self._output_text = output_text
        self._exc = exc
        self.calls: list[dict[str, Any]] = []

    def generate_text(
        self,
        *,
        messages: Sequence[dict[str, str]],
        model: str | None = None,
    ) -> str:
        self.calls.append({"messages": list(messages), "model": model})
        if self._exc is not None:
            raise self._exc
        if self._output_text is None:
            raise AssertionError("No fake LLM output configured.")
        return self._output_text


def _missing_openai_key() -> Any:
    raise ValueError("OPENAI_API_KEY is not configured.")


@pytest.fixture(autouse=True)
def _default_to_missing_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph_module, "get_llm_client", _missing_openai_key)


def _scope_request_payload(*, deny: bool = False) -> dict[str, object]:
    metadata: dict[str, str] = {"access": "deny"} if deny else {}
    return {
        "user_id": 101,
        "profile_id": 201,
        "profile_nick": "Nick",
        "metadata": metadata,
    }


def _initial_state(question: str, *, deny_scope: bool = False) -> dict[str, object]:
    return {
        "thread_id": "11111111-1111-1111-1111-111111111111",
        "run_id": "22222222-2222-2222-2222-222222222222",
        "user_question": question,
        "scope_request": _scope_request_payload(deny=deny_scope),
        "needs_clarification": False,
        "status": "running",
    }


def _node_order(graph: Any, payload: dict[str, object]) -> list[str]:
    order: list[str] = []
    for chunk in graph.stream(payload, stream_mode="updates"):
        order.extend(chunk.keys())
    return order


def test_supported_request_executes_full_run_path() -> None:
    graph = build_agent_graph()
    payload = _initial_state("What were total sales 2026-03-01 to 2026-03-07?")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "interpret_request",
        "route_decision",
        "run_report",
        "calc_metrics",
        "compose_answer",
    ]
    assert final_state.status is RunStatus.COMPLETED
    assert final_state.selected_report_id is ReportType.SALES_TOTAL
    assert final_state.tool_responses.run_report is not None
    assert final_state.tool_responses.run_report.result.metrics[0].value == 12345.67
    assert final_state.base_metrics["sales_total"] == Decimal("12345.67")
    assert len(final_state.derived_metrics) == 1
    assert final_state.derived_metrics[0].key == "sales_total_per_day"
    assert "sales_total=12345.67" in (final_state.final_answer or "")
    assert "sales_total_per_day=1763.67" in (final_state.final_answer or "")


def test_average_check_without_formula_policy_still_completes() -> None:
    graph = build_agent_graph()
    payload = _initial_state("What was average check 2026-03-01 to 2026-03-07?")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "interpret_request",
        "route_decision",
        "run_report",
        "calc_metrics",
        "compose_answer",
    ]
    assert final_state.status is RunStatus.COMPLETED
    assert final_state.selected_report_id is ReportType.AVERAGE_CHECK
    assert final_state.derived_metrics == []
    assert "calc_no_formulas_selected" in final_state.warnings


def test_missing_date_routes_to_clarify_without_report_execution() -> None:
    graph = build_agent_graph()
    payload = _initial_state("What were total sales?")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == ["resolve_scope", "interpret_request", "route_decision", "clarify"]
    assert final_state.status is RunStatus.CLARIFY
    assert final_state.needs_clarification is True
    assert final_state.tool_responses.run_report is None
    assert "date range" in (final_state.final_answer or "").lower()


@pytest.mark.parametrize(
    ("llm_payload", "expected_order", "expected_status", "expected_report_id"),
    [
        (
            {
                "intent": "get_kpi",
                "report_id": "sales_total",
                "filters": {"date_from": "2026-03-01", "date_to": "2026-03-07"},
                "needs_clarification": False,
                "clarification_question": None,
                "confidence": 0.95,
                "reasoning_notes": "Matched sales_total and extracted date range.",
            },
            [
                "resolve_scope",
                "interpret_request",
                "route_decision",
                "run_report",
                "calc_metrics",
                "compose_answer",
            ],
            RunStatus.COMPLETED,
            ReportType.SALES_TOTAL,
        ),
        (
            {
                "intent": "needs_clarification",
                "report_id": None,
                "filters": None,
                "needs_clarification": True,
                "clarification_question": "Please provide a date range.",
                "confidence": 0.52,
                "reasoning_notes": "Missing required date filter.",
            },
            ["resolve_scope", "interpret_request", "route_decision", "clarify"],
            RunStatus.CLARIFY,
            None,
        ),
        (
            {
                "intent": "unsupported_request",
                "report_id": None,
                "filters": None,
                "needs_clarification": False,
                "clarification_question": None,
                "confidence": 0.18,
                "reasoning_notes": "Unsupported domain request.",
            },
            ["resolve_scope", "interpret_request", "route_decision", "reject"],
            RunStatus.REJECTED,
            None,
        ),
    ],
)
def test_llm_interpretation_routes_based_on_model_output(
    monkeypatch: pytest.MonkeyPatch,
    llm_payload: dict[str, object],
    expected_order: list[str],
    expected_status: RunStatus,
    expected_report_id: ReportType | None,
) -> None:
    fake_client = _FakeLLMClient(output_text=json.dumps(llm_payload))
    monkeypatch.setattr(graph_module, "get_llm_client", lambda: fake_client)
    graph = build_agent_graph()
    payload = _initial_state("Interpret this request using model output.")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert len(fake_client.calls) >= 1
    assert order == expected_order
    assert final_state.status is expected_status
    assert final_state.selected_report_id is expected_report_id


def test_malformed_llm_output_routes_to_fallback_clarify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeLLMClient(output_text='{"intent": "get_kpi"}')
    monkeypatch.setattr(graph_module, "get_llm_client", lambda: fake_client)
    graph = build_agent_graph()
    payload = _initial_state("What were total sales 2026-03-01 to 2026-03-07?")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == ["resolve_scope", "interpret_request", "route_decision", "clarify"]
    assert final_state.status is RunStatus.CLARIFY
    assert "interpretation_contract_invalid" in final_state.warnings


def test_llm_timeout_error_propagates_from_interpret_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeout_error = LLMClientError(
        "OpenAI request timed out.",
        category=LLMErrorCategory.TIMEOUT,
        retryable=True,
    )
    fake_client = _FakeLLMClient(exc=timeout_error)
    monkeypatch.setattr(graph_module, "get_llm_client", lambda: fake_client)
    graph = build_agent_graph()

    with pytest.raises(LLMClientError) as exc_info:
        graph.invoke(_initial_state("What were total sales 2026-03-01 to 2026-03-07?"))

    assert exc_info.value.category is LLMErrorCategory.TIMEOUT


def test_missing_openai_key_uses_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback_called = False

    def _fallback_interpretation(_question: str) -> dict[str, object]:
        nonlocal fallback_called
        fallback_called = True
        return {
            "intent": "get_kpi",
            "report_id": "sales_total",
            "filters": {"date_from": "2026-03-01", "date_to": "2026-03-07"},
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.91,
            "reasoning_notes": "Fallback interpreter response.",
        }

    monkeypatch.setattr(graph_module, "_generate_interpretation_payload", _fallback_interpretation)
    monkeypatch.setattr(graph_module, "get_llm_client", _missing_openai_key)
    graph = build_agent_graph()

    final_state = AgentState.model_validate(
        graph.invoke(_initial_state("This path should use deterministic fallback."))
    )

    assert fallback_called is True
    assert final_state.status is RunStatus.COMPLETED
    assert final_state.selected_report_id is ReportType.SALES_TOTAL


def test_invalid_interpretation_output_routes_to_fallback_clarify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _invalid_interpretation_output(_question: str) -> dict[str, object]:
        return {
            "intent": "get_kpi",
            "report_id": "sales_total",
            "filters": {"date_from": "2026-03-01", "date_to": "2026-03-07"},
            "needs_clarification": False,
            "clarification_question": None,
            # Missing required "confidence" to force schema rejection.
        }

    monkeypatch.setattr(
        graph_module,
        "_generate_interpretation_payload",
        _invalid_interpretation_output,
    )
    graph = build_agent_graph()
    payload = _initial_state("What were total sales 2026-03-01 to 2026-03-07?")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == ["resolve_scope", "interpret_request", "route_decision", "clarify"]
    assert final_state.status is RunStatus.CLARIFY
    assert final_state.needs_clarification is True
    assert final_state.clarification_question
    assert "interpretation_contract_invalid" in final_state.warnings


def test_unsupported_request_routes_to_reject() -> None:
    graph = build_agent_graph()
    payload = _initial_state("Show payroll tax trend 2026-03-01 to 2026-03-07.")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == ["resolve_scope", "interpret_request", "route_decision", "reject"]
    assert final_state.status is RunStatus.REJECTED
    assert final_state.tool_responses.run_report is None
    assert "unsupported request" in (final_state.final_answer or "").lower()


def test_scope_denied_blocks_report_execution() -> None:
    graph = build_agent_graph()
    payload = _initial_state(
        "What were total sales 2026-03-01 to 2026-03-07?",
        deny_scope=True,
    )

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == ["resolve_scope", "interpret_request", "route_decision", "reject"]
    assert final_state.status is RunStatus.DENIED
    assert final_state.tool_responses.run_report is None
    assert "access denied" in (final_state.final_answer or "").lower()
