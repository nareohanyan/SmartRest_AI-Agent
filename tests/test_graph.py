"""End-to-end tests for the minimal Task 9 LangGraph workflow."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.agent.graph import build_agent_graph
from app.schemas.agent import AgentState, RunStatus
from app.schemas.reports import ReportType


def _scope_request_payload(*, deny: bool = False) -> dict[str, object]:
    metadata: dict[str, str] = {"access": "deny"} if deny else {}
    return {
        "user_id": "u-1",
        "profile_id": "p-1",
        "profile_nick": "Nick",
        "metadata": metadata,
    }


def _initial_state(question: str, *, deny_scope: bool = False) -> dict[str, object]:
    return {
        "thread_id": "thread-1",
        "run_id": "run-1",
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
