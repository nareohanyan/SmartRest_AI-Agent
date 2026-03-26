"""End-to-end tests for hybrid planning graph workflow."""

from __future__ import annotations

import json
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

import pytest

import app.agent.graph as graph_module
from app.agent.graph import _reject_node, build_agent_graph
from app.agent.llm.exceptions import LLMClientError
from app.agent.tool_registry import ToolId
from app.schemas.agent import AgentState, LLMErrorCategory, PolicyRoute, RunStatus
from app.schemas.analysis import DimensionName, MetricName
from app.schemas.reports import ReportType
from app.schemas.tools import AccessStatus, ToolOperation


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


class _ScopeOverrideRegistry:
    _DYNAMIC_TOOL_IDS = {
        ToolId.FETCH_TOTAL_METRIC,
        ToolId.FETCH_BREAKDOWN,
        ToolId.FETCH_TIMESERIES,
        ToolId.ATTACH_BREAKDOWN_SHARE,
        ToolId.TOP_K,
        ToolId.BOTTOM_K,
        ToolId.MOVING_AVERAGE,
        ToolId.TREND_SLOPE,
    }

    def __init__(self, *, scope_overrides: dict[str, object]) -> None:
        self._base = graph_module.get_tool_registry()
        self._scope_overrides = scope_overrides
        self.calls: list[str] = []

    def invoke(self, tool_id: ToolId | str, request: Any) -> Any:
        normalized_tool_id = ToolId(tool_id)
        self.calls.append(normalized_tool_id.value)
        if normalized_tool_id is ToolId.RESOLVE_SCOPE:
            resolved = self._base.invoke(normalized_tool_id, request)
            return resolved.model_copy(update=self._scope_overrides)
        if normalized_tool_id in self._DYNAMIC_TOOL_IDS:
            raise AssertionError(
                f"Dynamic tool `{normalized_tool_id.value}` should not run when policy denies."
            )
        return self._base.invoke(normalized_tool_id, request)


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


def _scope_request_payload(
    *,
    deny: bool = False,
    metadata_overrides: dict[str, str] | None = None,
    requested_branch_ids: list[str] | None = None,
    requested_export_mode: str | None = None,
) -> dict[str, object]:
    metadata: dict[str, str] = {"access": "deny"} if deny else {}
    metadata.update(metadata_overrides or {})
    payload: dict[str, object] = {
        "user_id": 101,
        "profile_id": 201,
        "profile_nick": "Nick",
        "metadata": metadata,
    }
    if requested_branch_ids is not None:
        payload["requested_branch_ids"] = requested_branch_ids
    if requested_export_mode is not None:
        payload["requested_export_mode"] = requested_export_mode
    return payload


def _initial_state(
    question: str,
    *,
    deny_scope: bool = False,
    scope_payload_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    scope_payload = _scope_request_payload(deny=deny_scope)
    if scope_payload_overrides:
        scope_payload = {**scope_payload, **scope_payload_overrides}
    return {
        "chat_id": "11111111-1111-1111-1111-111111111111",
        "run_id": "22222222-2222-2222-2222-222222222222",
        "user_question": question,
        "scope_request": scope_payload,
        "needs_clarification": False,
        "status": "running",
    }


def _node_order(graph: Any, payload: dict[str, object]) -> list[str]:
    order: list[str] = []
    for chunk in graph.stream(payload, stream_mode="updates"):
        order.extend(chunk.keys())
    return order


def _plan_envelope(plan: dict[str, object], *, confidence: float = 0.99) -> str:
    return json.dumps({"plan": plan, "confidence": confidence})


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


def test_hy_supported_request_executes_legacy_report_path() -> None:
    graph = build_agent_graph()
    payload = _initial_state(
        "Ի՞նչ էր ընդհանուր վաճառքը 2026-03-01 to 2026-03-07 ժամանակահատվածում։"
    )

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


def test_ru_comparison_routes_to_dynamic_comparison_path() -> None:
    graph = build_agent_graph()
    payload = _initial_state("Сравни продажи 2026-03-10 to 2026-03-16 с предыдущим периодом.")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "plan_analysis",
        "policy_gate",
        "route_decision",
        "run_comparison",
        "compose_answer",
    ]
    assert final_state.status is RunStatus.COMPLETED
    assert final_state.policy_route is not None
    assert final_state.policy_route.value == "run_comparison"
    trace_step_ids = [step.step_id for step in final_state.execution_trace]
    assert trace_step_ids == [
        "tool.resolve_scope",
        "tool.fetch_total_metric.current",
        "tool.fetch_total_metric.previous",
        "tool.compute_scalar_metrics.comparison",
    ]
    assert all(step.status.value == "success" for step in final_state.execution_trace)
    assert "tool:synthetic_data" in final_state.warnings


def test_compound_kpi_request_routes_to_multi_report_path() -> None:
    graph = build_agent_graph()
    payload = _initial_state(
        "What were total sales and order count 2026-03-01 to 2026-03-07?"
    )

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "plan_analysis",
        "policy_gate",
        "route_decision",
        "run_multi_report",
        "compose_answer",
    ]
    assert final_state.status is RunStatus.COMPLETED
    assert final_state.policy_route is PolicyRoute.RUN_MULTI_REPORT
    assert len(final_state.legacy_task_results) == 2
    assert all(result.status == "completed" for result in final_state.legacy_task_results)
    assert "Total sales from 2026-03-01 to 2026-03-07 were 12345.67." in (
        final_state.final_answer or ""
    )
    assert "Order count from 2026-03-01 to 2026-03-07 was 345.00." in (
        final_state.final_answer or ""
    )


def test_compound_request_returns_partial_success_for_unsupported_task() -> None:
    graph = build_agent_graph()
    payload = _initial_state(
        "What were total sales this month and how many couriers did delivery this month?"
    )

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "plan_analysis",
        "policy_gate",
        "route_decision",
        "run_multi_report",
        "compose_answer",
    ]
    assert final_state.status is RunStatus.COMPLETED
    assert final_state.policy_route is PolicyRoute.RUN_MULTI_REPORT
    assert any(result.status == "completed" for result in final_state.legacy_task_results)
    assert any(result.status == "unsupported" for result in final_state.legacy_task_results)
    assert "planner_partial_multi_task" in final_state.warnings
    assert "I couldn't answer" in (final_state.final_answer or "")


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
    assert "060 44 55 66" in (final_state.final_answer or "")


def test_reject_node_uses_russian_fallback_for_granted_scope() -> None:
    state = AgentState.model_validate(
        {
            "chat_id": "11111111-1111-1111-1111-111111111111",
            "run_id": "22222222-2222-2222-2222-222222222222",
            "user_question": "Покажи неподдерживаемый отчет.",
            "user_scope": {
                "status": AccessStatus.GRANTED.value,
                "allowed_report_ids": [ReportType.SALES_TOTAL.value],
            },
            "needs_clarification": False,
            "status": RunStatus.RUNNING.value,
        }
    )

    result = _reject_node(state)

    assert result["status"] is RunStatus.REJECTED
    assert result["final_answer"] is not None
    assert "sales_total" in result["final_answer"]
    assert "Неподдерживаемый запрос." in result["final_answer"]


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
    assert final_state.status is RunStatus.ONBOARDING
    assert final_state.needs_clarification is False
    assert final_state.final_answer == "Ողջու՜յն։ Ինչո՞վ կարող եմ օգնել ձեզ այսօր։"
    assert final_state.clarification_question is None


def test_smalltalk_in_russian_routes_to_smalltalk_answer() -> None:
    graph = build_agent_graph()
    payload = _initial_state("привет")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "plan_analysis",
        "policy_gate",
        "route_decision",
        "smalltalk",
    ]
    assert final_state.status is RunStatus.ONBOARDING
    assert final_state.needs_clarification is False
    assert final_state.final_answer == "Здравствуйте. Чем я могу вам сегодня помочь?"
    assert final_state.clarification_question is None


def test_casual_smalltalk_in_english_routes_to_smalltalk_answer() -> None:
    graph = build_agent_graph()
    payload = _initial_state("hello what's up")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "plan_analysis",
        "policy_gate",
        "route_decision",
        "smalltalk",
    ]
    assert final_state.status is RunStatus.ONBOARDING
    assert final_state.needs_clarification is False
    assert final_state.final_answer == "Hello. Nice to see you here."
    assert final_state.clarification_question is None


def test_casual_smalltalk_in_armenian_routes_to_smalltalk_answer() -> None:
    graph = build_agent_graph()
    payload = _initial_state("ինչ կա")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "plan_analysis",
        "policy_gate",
        "route_decision",
        "smalltalk",
    ]
    assert final_state.status is RunStatus.ONBOARDING
    assert final_state.needs_clarification is False
    assert final_state.final_answer == "Ողջու՜յն։ Ինչո՞վ կարող եմ օգնել ձեզ այսօր։"
    assert final_state.clarification_question is None


def test_typo_russian_greeting_routes_to_smalltalk_answer() -> None:
    graph = build_agent_graph()
    payload = _initial_state("здраствуйте")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "plan_analysis",
        "policy_gate",
        "route_decision",
        "smalltalk",
    ]
    assert final_state.status is RunStatus.ONBOARDING
    assert final_state.needs_clarification is False
    assert final_state.final_answer == "Здравствуйте. Чем я могу вам сегодня помочь?"
    assert final_state.clarification_question is None


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


def test_greeting_with_business_terms_is_not_smalltalk() -> None:
    graph = build_agent_graph()
    payload = _initial_state("hello compare branch")

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


def test_high_priority_business_trigger_blocks_smalltalk() -> None:
    graph = build_agent_graph()
    payload = _initial_state("hello earnings")

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


def test_branch_permission_denied_blocks_execution_before_tool_calls() -> None:
    graph = build_agent_graph()
    payload = _initial_state(
        "What were total sales 2026-03-01 to 2026-03-07?",
        scope_payload_overrides={
            "metadata": {"allow_branch_ids": "branch_1"},
            "requested_branch_ids": ["branch_2"],
        },
    )

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == ["resolve_scope", "plan_analysis", "policy_gate", "route_decision", "reject"]
    assert final_state.status is RunStatus.REJECTED
    assert "policy:branch_not_allowed" in final_state.warnings
    assert final_state.tool_responses.run_report is None


def test_export_mode_permission_denied_blocks_execution() -> None:
    graph = build_agent_graph()
    payload = _initial_state(
        "What were total sales 2026-03-01 to 2026-03-07?",
        scope_payload_overrides={
            "metadata": {"allow_export_modes": "csv"},
            "requested_export_mode": "pdf",
        },
    )

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == ["resolve_scope", "plan_analysis", "policy_gate", "route_decision", "reject"]
    assert final_state.status is RunStatus.REJECTED
    assert "policy:export_mode_not_allowed" in final_state.warnings
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


def test_low_confidence_llm_plan_falls_back_with_distinct_warning(
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
            "reasoning_notes": "Low confidence test payload.",
        },
        "confidence": 0.3,
    }
    fake_client = _FakeLLMClient(output_text=json.dumps(llm_payload))
    monkeypatch.setattr(graph_module, "get_llm_client", lambda: fake_client)
    graph = build_agent_graph()

    final_state = AgentState.model_validate(
        graph.invoke(_initial_state("What were total sales 2026-03-01 to 2026-03-07?"))
    )

    assert final_state.status is RunStatus.COMPLETED
    assert final_state.plan_source.value == "fallback"
    assert "planner_low_confidence_fallback" in final_state.warnings
    assert "planner_contract_or_config_fallback" not in final_state.warnings
    assert "planner_llm_error_fallback" not in final_state.warnings


def test_llm_error_falls_back_with_distinct_warning(
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

    final_state = AgentState.model_validate(
        graph.invoke(_initial_state("What were total sales 2026-03-01 to 2026-03-07?"))
    )

    assert final_state.status is RunStatus.COMPLETED
    assert final_state.plan_source.value == "fallback"
    assert "planner_llm_error_fallback" in final_state.warnings
    assert "planner_low_confidence_fallback" not in final_state.warnings


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

    assert len(fake_client.calls) == 0
    assert final_state.status is RunStatus.ONBOARDING
    assert final_state.needs_clarification is False
    assert final_state.policy_route is not None
    assert final_state.policy_route.value == "smalltalk"
    assert "response_llm_fallback" not in final_state.warnings


def test_smalltalk_stays_deterministic_even_when_llm_is_available(
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

    assert len(fake_client.calls) == 0
    assert final_state.status is RunStatus.ONBOARDING
    assert final_state.needs_clarification is False
    assert final_state.final_answer == "Ողջու՜յն։ Ինչո՞վ կարող եմ օգնել ձեզ այսօր։"
    assert final_state.clarification_question is None


@pytest.mark.parametrize(
    ("plan_payload", "scope_overrides", "expected_reason_code"),
    [
        (
            {
                "intent": "comparison",
                "retrieval": {
                    "mode": "total",
                    "metric": "sales_total",
                    "date_from": "2026-03-10",
                    "date_to": "2026-03-16",
                    "dimension": None,
                },
                "compare_to_previous_period": True,
                "previous_period_retrieval": {
                    "mode": "total",
                    "metric": "sales_total",
                    "date_from": "2026-03-03",
                    "date_to": "2026-03-09",
                    "dimension": None,
                },
                "scalar_calculations": [],
                "include_moving_average": False,
                "moving_average_window": 3,
                "include_trend_slope": False,
                "ranking": None,
                "needs_clarification": False,
                "clarification_question": None,
                "reasoning_notes": "Comparison contract test.",
            },
            {"allowed_tool_operations": [ToolOperation.MOVING_AVERAGE]},
            "tool_not_allowed",
        ),
        (
            {
                "intent": "ranking",
                "retrieval": {
                    "mode": "breakdown",
                    "metric": "sales_total",
                    "date_from": "2026-03-10",
                    "date_to": "2026-03-16",
                    "dimension": "source",
                },
                "compare_to_previous_period": False,
                "previous_period_retrieval": None,
                "scalar_calculations": [],
                "include_moving_average": False,
                "moving_average_window": 3,
                "include_trend_slope": False,
                "ranking": {
                    "mode": "top_k",
                    "k": 3,
                    "metric_key": "value",
                    "direction": "desc",
                },
                "needs_clarification": False,
                "clarification_question": None,
                "reasoning_notes": "Ranking contract test.",
            },
            {"allowed_dimension_ids": [DimensionName.DAY.value]},
            "dimension_not_allowed",
        ),
        (
            {
                "intent": "trend",
                "retrieval": {
                    "mode": "timeseries",
                    "metric": "sales_total",
                    "date_from": "2026-03-10",
                    "date_to": "2026-03-16",
                    "dimension": "day",
                },
                "compare_to_previous_period": False,
                "previous_period_retrieval": None,
                "scalar_calculations": [],
                "include_moving_average": True,
                "moving_average_window": 3,
                "include_trend_slope": True,
                "ranking": None,
                "needs_clarification": False,
                "clarification_question": None,
                "reasoning_notes": "Trend contract test.",
            },
            {"allowed_metric_ids": [MetricName.ORDER_COUNT.value]},
            "metric_not_allowed",
        ),
    ],
)
def test_dynamic_routes_do_not_execute_tools_when_permission_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    plan_payload: dict[str, object],
    scope_overrides: dict[str, object],
    expected_reason_code: str,
) -> None:
    fake_client = _FakeLLMClient(output_text=_plan_envelope(plan_payload))
    restricted_registry = _ScopeOverrideRegistry(scope_overrides=scope_overrides)
    monkeypatch.setattr(graph_module, "get_llm_client", lambda: fake_client)
    monkeypatch.setattr(
        graph_module,
        "get_settings",
        lambda: _settings(planner_mode="llm", planner_fallback_enabled=False),
    )
    monkeypatch.setattr(graph_module, "get_tool_registry", lambda: restricted_registry)
    graph = build_agent_graph()

    final_state = AgentState.model_validate(graph.invoke(_initial_state("permission test")))

    assert final_state.status is RunStatus.REJECTED
    assert final_state.policy_route is not None
    assert final_state.policy_route.value == "reject"
    assert f"policy:{expected_reason_code}" in final_state.warnings
    assert restricted_registry.calls == [ToolId.RESOLVE_SCOPE.value]
    assert [step.step_id for step in final_state.execution_trace] == ["tool.resolve_scope"]
