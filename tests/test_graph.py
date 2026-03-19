"""End-to-end tests for hybrid planning graph workflow."""

from __future__ import annotations

import json
from collections.abc import Sequence
from types import SimpleNamespace
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


def _settings(**overrides: object) -> SimpleNamespace:
    payload = {
        "planner_mode": "hybrid",
        "planner_fallback_enabled": True,
        "planner_min_confidence": 0.75,
        "planner_max_date_range_days": 366,
        "planner_max_tool_calls": 6,
        "planner_allow_safe_general_topics": True,
        "openai_api_key": None,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


@pytest.fixture(autouse=True)
def _default_runtime_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph_module, "get_llm_client", _missing_openai_key)
    monkeypatch.setattr(graph_module, "get_settings", lambda: _settings())


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


def test_supported_request_executes_legacy_report_path() -> None:
    graph = build_agent_graph()
    payload = _initial_state("What were total sales 2026-03-01 to 2026-03-07?")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "plan_analysis",
        "policy_gate",
        "route_decision",
        "prepare_legacy_report",
        "run_report",
        "calc_metrics",
        "compose_answer",
    ]
    assert final_state.status is RunStatus.COMPLETED
    assert final_state.selected_report_id is ReportType.SALES_TOTAL
    assert final_state.tool_responses.run_report is not None
    assert "sales_total=12345.67" in (final_state.final_answer or "")


def test_missing_date_routes_to_clarify() -> None:
    graph = build_agent_graph()
    payload = _initial_state("What were total sales?")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == ["resolve_scope", "plan_analysis", "policy_gate", "route_decision", "clarify"]
    assert final_state.status is RunStatus.CLARIFY
    assert final_state.needs_clarification is True


def test_unsupported_request_routes_to_safe_answer() -> None:
    graph = build_agent_graph()
    payload = _initial_state("How to optimize payroll taxes for this quarter?")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "plan_analysis",
        "policy_gate",
        "route_decision",
        "safe_answer",
    ]
    assert final_state.status is RunStatus.REJECTED
    assert "smartrest analytics" in (final_state.final_answer or "").lower()


def test_smalltalk_in_armenian_routes_to_smalltalk_answer() -> None:
    graph = build_agent_graph()
    payload = _initial_state("բարև")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "plan_analysis",
        "policy_gate",
        "route_decision",
        "smalltalk",
    ]
    assert final_state.status is RunStatus.CLARIFY
    assert final_state.needs_clarification is True
    assert "Բարև" in (final_state.final_answer or "")
    assert final_state.clarification_question == final_state.final_answer


def test_mixed_greeting_with_business_text_is_not_smalltalk() -> None:
    graph = build_agent_graph()
    payload = _initial_state("բարև ինձ տուր էս ամսվա ամենաեկամտաբեր ապրանքը")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "plan_analysis",
        "policy_gate",
        "route_decision",
        "safe_answer",
    ]
    assert final_state.status is RunStatus.REJECTED
    assert final_state.policy_route is not None
    assert final_state.policy_route.value == "safe_answer"


def test_scope_denied_blocks_execution() -> None:
    graph = build_agent_graph()
    payload = _initial_state(
        "What were total sales 2026-03-01 to 2026-03-07?",
        deny_scope=True,
    )

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == ["resolve_scope", "plan_analysis", "policy_gate", "route_decision", "reject"]
    assert final_state.status is RunStatus.DENIED
    assert final_state.tool_responses.run_report is None


def test_llm_planning_valid_payload_is_used_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm_payload = {
        "plan": {
            "intent": "metric_total",
            "retrieval": {
                "mode": "total",
                "metric": "sales_total",
                "date_from": "2026-03-01",
                "date_to": "2026-03-07",
                "dimension": None,
            },
            "compare_to_previous_period": False,
            "previous_period_retrieval": None,
            "scalar_calculations": [],
            "include_moving_average": False,
            "moving_average_window": 3,
            "include_trend_slope": False,
            "ranking": None,
            "needs_clarification": False,
            "clarification_question": None,
            "reasoning_notes": "Direct metric total query.",
        },
        "confidence": 0.95,
    }
    fake_client = _FakeLLMClient(output_text=json.dumps(llm_payload))
    monkeypatch.setattr(graph_module, "get_llm_client", lambda: fake_client)
    graph = build_agent_graph()

    final_state = AgentState.model_validate(
        graph.invoke(_initial_state("Use LLM plan output for this request."))
    )

    assert len(fake_client.calls) >= 1
    assert final_state.status is RunStatus.COMPLETED
    assert final_state.plan_source.value == "llm"
    assert final_state.plan_confidence == 0.95


def test_invalid_llm_plan_payload_falls_back_to_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeLLMClient(
        output_text='{"plan": {"intent": "metric_total"}, "confidence": 0.99}'
    )
    monkeypatch.setattr(graph_module, "get_llm_client", lambda: fake_client)
    graph = build_agent_graph()

    final_state = AgentState.model_validate(
        graph.invoke(_initial_state("What were total sales 2026-03-01 to 2026-03-07?"))
    )

    assert final_state.status is RunStatus.COMPLETED
    assert final_state.plan_source.value == "fallback"
    assert "planner_contract_or_config_fallback" in final_state.warnings


def test_llm_error_propagates_when_mode_is_llm_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeout_error = LLMClientError(
        "OpenAI request timed out.",
        category=LLMErrorCategory.TIMEOUT,
        retryable=True,
    )
    fake_client = _FakeLLMClient(exc=timeout_error)
    monkeypatch.setattr(graph_module, "get_llm_client", lambda: fake_client)
    monkeypatch.setattr(
        graph_module,
        "get_settings",
        lambda: _settings(planner_mode="llm", planner_fallback_enabled=False),
    )
    graph = build_agent_graph()

    with pytest.raises(LLMClientError) as exc_info:
        graph.invoke(_initial_state("What were total sales 2026-03-01 to 2026-03-07?"))

    assert exc_info.value.category is LLMErrorCategory.TIMEOUT


def test_smalltalk_bypasses_llm_even_in_llm_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeout_error = LLMClientError(
        "OpenAI request timed out.",
        category=LLMErrorCategory.TIMEOUT,
        retryable=True,
    )
    fake_client = _FakeLLMClient(exc=timeout_error)
    monkeypatch.setattr(graph_module, "get_llm_client", lambda: fake_client)
    monkeypatch.setattr(
        graph_module,
        "get_settings",
        lambda: _settings(
            planner_mode="llm",
            planner_fallback_enabled=False,
            openai_api_key="test-key",
        ),
    )
    graph = build_agent_graph()

    final_state = AgentState.model_validate(graph.invoke(_initial_state("բարև")))

    assert len(fake_client.calls) == 1
    assert final_state.status is RunStatus.CLARIFY
    assert final_state.needs_clarification is True
    assert final_state.policy_route is not None
    assert final_state.policy_route.value == "smalltalk"
    assert "response_llm_fallback" in final_state.warnings


def test_smalltalk_uses_llm_response_generation_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeLLMClient(output_text="Բարև, ինչպե՞ս կարող եմ օգնել SmartRest տվյալներով։")
    monkeypatch.setattr(graph_module, "get_llm_client", lambda: fake_client)
    monkeypatch.setattr(
        graph_module,
        "get_settings",
        lambda: _settings(openai_api_key="test-key"),
    )
    graph = build_agent_graph()

    final_state = AgentState.model_validate(graph.invoke(_initial_state("բարև")))

    assert len(fake_client.calls) == 1
    assert final_state.status is RunStatus.CLARIFY
    assert final_state.needs_clarification is True
    assert final_state.final_answer == "Բարև, ինչպե՞ս կարող եմ օգնել SmartRest տվյալներով։"
    assert final_state.clarification_question == final_state.final_answer
