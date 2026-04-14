"""End-to-end tests for hybrid planning graph workflow."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

import app.agent.graph as graph_module
import app.agent.report_tools as report_tools
from app.agent.graph import _build_retrieval_scope, _reject_node, build_agent_graph
from app.agent.llm.exceptions import LLMClientError
from app.agent.report_tools import resolve_scope_tool
from app.agent.tool_registry import ToolId
from app.agent.tools import business_insights as business_insights_tools
from app.agent.tools import retrieval as retrieval_tools
from app.schemas.agent import AgentState, LLMErrorCategory, PolicyRoute, RunStatus
from app.schemas.analysis import (
    BreakdownItem,
    BreakdownResponse,
    CustomerSummaryResponse,
    DimensionName,
    ItemPerformanceItem,
    ItemPerformanceMetric,
    ItemPerformanceResponse,
    MetricName,
    TimeseriesPoint,
    TimeseriesResponse,
    TotalMetricResponse,
)
from app.schemas.reports import ReportMetric, ReportResult, ReportType
from app.schemas.tools import AccessStatus, RunReportResponse, ToolOperation


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
    monkeypatch.setattr(
        report_tools,
        "get_canonical_identity_resolver",
        lambda: type(
            "_Resolver",
            (),
            {
                "resolve": staticmethod(
                    lambda **kwargs: None
                    if kwargs.get("profile_id") == 999
                    else type(
                        "_Resolution",
                        (),
                        {
                            "source_system_id": 1,
                            "canonical_profile_id": 1,
                            "canonical_user_id": 1,
                        },
                    )()
                )
            },
        )(),
    )
    monkeypatch.setattr(report_tools, "run_smartrest_report", _fake_run_smartrest_report)
    monkeypatch.setattr(
        retrieval_tools,
        "get_live_analytics_service",
        lambda: _FakeLiveAnalyticsService(),
    )
    monkeypatch.setattr(
        business_insights_tools,
        "LiveBusinessToolsService",
        lambda: _FakeBusinessToolsService(),
    )
    graph_module.get_tool_registry.cache_clear()
    try:
        yield
    finally:
        if hasattr(graph_module.get_tool_registry, "cache_clear"):
            graph_module.get_tool_registry.cache_clear()


def _scope_request_payload(
    *,
    deny: bool = False,
    metadata_overrides: dict[str, str] | None = None,
    requested_branch_ids: list[str] | None = None,
    requested_export_mode: str | None = None,
) -> dict[str, object]:
    metadata: dict[str, str] = {}
    metadata.update(metadata_overrides or {})
    payload: dict[str, object] = {
        "user_id": 101,
        "profile_id": 999 if deny else 201,
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


def _fake_run_smartrest_report(request: Any, *, profile_id: int) -> RunReportResponse:
    del profile_id
    metric_map = {
        ReportType.SALES_TOTAL: [ReportMetric(label="sales_total", value=12345.67)],
        ReportType.ORDER_COUNT: [ReportMetric(label="order_count", value=345.0)],
        ReportType.AVERAGE_CHECK: [ReportMetric(label="average_check", value=35.78)],
        ReportType.SALES_BY_SOURCE: [
            ReportMetric(label="in_store", value=10000.0),
            ReportMetric(label="takeaway", value=2345.67),
        ],
    }
    if request.report_id is ReportType.SALES_BY_SOURCE and request.filters.source is not None:
        metric_map[ReportType.SALES_BY_SOURCE] = [
            ReportMetric(label=request.filters.source, value=2345.67)
        ]
    return RunReportResponse(
        result=ReportResult(
            report_id=request.report_id,
            filters=request.filters,
            metrics=metric_map[request.report_id],
        ),
        warnings=["smartrest_backend_live_data"],
    )


class _FakeLiveAnalyticsService:
    def get_total_metric(self, request: Any) -> TotalMetricResponse:
        previous = request.date_to < date(2026, 3, 10)
        value_map = {
            MetricName.SALES_TOTAL: 9000 if previous else 10000,
            MetricName.ORDER_COUNT: 300 if previous else 345,
            MetricName.AVERAGE_CHECK: 30 if previous else 35,
        }
        value = value_map.get(request.metric, 10000)
        return TotalMetricResponse(
            metric=request.metric,
            date_from=request.date_from,
            date_to=request.date_to,
            value=value,
            base_metrics={
                "sales_total": 10000,
                "order_count": 345,
                "day_count": 7,
            },
            warnings=[],
        )

    def get_breakdown(self, request: Any) -> BreakdownResponse:
        items = [
            BreakdownItem(label="in_store", value=10000),
            BreakdownItem(label="takeaway", value=2345.67),
        ]
        return BreakdownResponse(
            metric=request.metric,
            dimension=request.dimension,
            date_from=request.date_from,
            date_to=request.date_to,
            items=items,
            total_value=sum(item.value for item in items),
            warnings=[],
        )

    def get_timeseries(self, request: Any) -> TimeseriesResponse:
        return TimeseriesResponse(
            metric=request.metric,
            dimension=request.dimension,
            date_from=request.date_from,
            date_to=request.date_to,
            points=[
                TimeseriesPoint(bucket=date(2026, 3, 10), value=1000),
                TimeseriesPoint(bucket=date(2026, 3, 11), value=1100),
            ],
            warnings=[],
        )


class _FakeBusinessToolsService:
    def get_item_performance(self, request: Any) -> ItemPerformanceResponse:
        return ItemPerformanceResponse(
            metric=request.metric or ItemPerformanceMetric.ITEM_REVENUE,
            date_from=request.date_from,
            date_to=request.date_to,
            ranking_mode=request.ranking_mode,
            items=[ItemPerformanceItem(menu_item_id=1, name="Lahmajo", value=123)],
            warnings=[],
        )

    def get_customer_summary(self, request: Any) -> CustomerSummaryResponse:
        return CustomerSummaryResponse(
            date_from=request.date_from,
            date_to=request.date_to,
            unique_clients=12,
            identified_order_count=48,
            total_order_count=60,
            average_orders_per_identified_client=4,
            warnings=[],
        )

    def get_receipt_summary(self, request: Any):
        from app.schemas.analysis import ReceiptSummaryResponse

        return ReceiptSummaryResponse(
            date_from=request.date_from,
            date_to=request.date_to,
            receipt_count=15,
            linked_order_count=14,
            status_counts={"30": 10, "50": 5},
            warnings=[],
        )


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


def test_build_retrieval_scope_uses_requested_branch_ids_when_present() -> None:
    state = AgentState.model_validate(
        _initial_state(
            "Show sales by branch 2026-03-01 to 2026-03-07",
            scope_payload_overrides={"requested_branch_ids": ["branch_4", "9", "invalid"]},
        )
    )
    assert state.scope_request is not None
    state.user_scope = resolve_scope_tool(state.scope_request)

    scope = _build_retrieval_scope(state)

    assert scope is not None
    assert scope.profile_id == 201
    assert scope.branch_ids == [4, 9]


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


def test_item_business_query_routes_to_business_tool_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_registry = graph_module.get_tool_registry()

    class _BusinessRegistry:
        def invoke(self, tool_id: ToolId | str, request: Any) -> Any:
            normalized = ToolId(tool_id)
            if normalized is ToolId.FETCH_ITEM_PERFORMANCE:
                return ItemPerformanceResponse(
                    metric=request.metric,
                    date_from=request.date_from,
                    date_to=request.date_to,
                    ranking_mode=request.ranking_mode,
                    items=[ItemPerformanceItem(menu_item_id=1, name="Lahmajo", value=123)],
                    warnings=[],
                )
            return base_registry.invoke(normalized, request)

    monkeypatch.setattr(graph_module, "get_tool_registry", lambda: _BusinessRegistry())
    graph = build_agent_graph()
    payload = _initial_state("Show top 5 menu items 2026-03-01 to 2026-03-07")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "plan_analysis",
        "policy_gate",
        "route_decision",
        "run_business_query",
        "compose_answer",
    ]
    assert final_state.status is RunStatus.COMPLETED
    assert final_state.policy_route is PolicyRoute.RUN_BUSINESS_QUERY
    assert "Lahmajo" in (final_state.final_answer or "")
    assert all(result.status == "completed" for result in final_state.legacy_task_results)


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
        "clarify",
    ]
    assert final_state.status is RunStatus.CLARIFY
    assert final_state.policy_route is not None
    assert final_state.policy_route.value == "clarify"


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
        "clarify",
    ]
    assert final_state.status is RunStatus.CLARIFY
    assert final_state.policy_route is not None
    assert final_state.policy_route.value == "clarify"


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
    assert final_state.plan_source is not None
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
    assert final_state.plan_source is not None
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
    assert final_state.plan_source is not None
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
    assert final_state.plan_source is not None
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
