"""Minimal LangGraph workflow for Task 9."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from langgraph.graph import END, StateGraph

from app.agent.calc_policy import select_calculation_specs
from app.agent.calc_tools import compute_metrics_tool
from app.agent.metrics_mapper import map_report_response_to_base_metrics
from app.agent.report_tools import resolve_scope_tool, run_report_tool
from app.schemas.agent import AgentState, IntentType, RunStatus
from app.schemas.calculations import ComputeMetricsRequest
from app.schemas.reports import ReportFilters, ReportRequest, ReportType
from app.schemas.tools import AccessStatus, RunReportRequest

_DATE_RANGE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})")


def _detect_report_id(question: str) -> ReportType | None:
    text = question.lower()
    if "sales by source" in text or "by source" in text or "source" in text:
        return ReportType.SALES_BY_SOURCE
    if "average check" in text or "avg check" in text or "average ticket" in text:
        return ReportType.AVERAGE_CHECK
    if "order count" in text or "orders" in text:
        return ReportType.ORDER_COUNT
    if "total sales" in text or "sales" in text:
        return ReportType.SALES_TOTAL
    return None


def _extract_filters(question: str) -> ReportFilters | None:
    match = _DATE_RANGE_PATTERN.search(question)
    if match is None:
        return None

    try:
        date_from = date.fromisoformat(match.group(1))
        date_to = date.fromisoformat(match.group(2))
        return ReportFilters(date_from=date_from, date_to=date_to)
    except ValueError:
        return None


def _resolve_scope_node(state: AgentState) -> dict[str, Any]:
    if state.scope_request is None:
        return {
            "status": RunStatus.DENIED,
            "final_answer": "Access denied: missing scope request.",
            "warnings": [*state.warnings, "missing_scope_request"],
        }

    scope_response = resolve_scope_tool(state.scope_request)
    tool_responses = state.tool_responses.model_copy(deep=True)
    tool_responses.resolve_scope = scope_response
    return {"user_scope": scope_response, "tool_responses": tool_responses}


def _interpret_request_node(state: AgentState) -> dict[str, Any]:
    selected_report_id = _detect_report_id(state.user_question)
    if selected_report_id is None:
        return {
            "intent": IntentType.UNSUPPORTED_REQUEST,
            "selected_report_id": None,
            "filters": None,
            "needs_clarification": False,
            "clarification_question": None,
        }

    filters = _extract_filters(state.user_question)
    if filters is None:
        return {
            "intent": IntentType.NEEDS_CLARIFICATION,
            "selected_report_id": selected_report_id,
            "filters": None,
            "needs_clarification": True,
            "clarification_question": (
                "Please provide a date range using YYYY-MM-DD to YYYY-MM-DD."
            ),
        }

    intent = (
        IntentType.BREAKDOWN_KPI
        if selected_report_id is ReportType.SALES_BY_SOURCE
        else IntentType.GET_KPI
    )
    return {
        "intent": intent,
        "selected_report_id": selected_report_id,
        "filters": filters,
        "needs_clarification": False,
        "clarification_question": None,
    }


def _route_decision_node(state: AgentState) -> dict[str, Any]:
    return {}


def _select_next_route(state: AgentState) -> str:
    if state.user_scope is None or state.user_scope.status is AccessStatus.DENIED:
        return "reject"
    if state.needs_clarification or state.intent is IntentType.NEEDS_CLARIFICATION:
        return "clarify"
    if state.intent is IntentType.UNSUPPORTED_REQUEST or state.selected_report_id is None:
        return "reject"
    if state.filters is None:
        return "clarify"
    return "run_report"


def _run_report_node(state: AgentState) -> dict[str, Any]:
    if state.scope_request is None or state.selected_report_id is None or state.filters is None:
        return {
            "status": RunStatus.FAILED,
            "final_answer": "Run failed: missing required report execution context.",
            "warnings": [*state.warnings, "run_report_missing_context"],
        }

    run_request = RunReportRequest(
        user_id=state.scope_request.user_id,
        profile_id=state.scope_request.profile_id,
        profile_nick=state.scope_request.profile_nick,
        request=ReportRequest(
            report_id=state.selected_report_id,
            filters=state.filters,
        ),
    )
    run_response = run_report_tool(run_request)

    tool_responses = state.tool_responses.model_copy(deep=True)
    tool_responses.run_report = run_response
    return {
        "tool_responses": tool_responses,
        "warnings": [*state.warnings, *run_response.warnings],
    }


def _calc_metrics_node(state: AgentState) -> dict[str, Any]:
    run_response = state.tool_responses.run_report
    if run_response is None:
        return {
            "status": RunStatus.FAILED,
            "final_answer": "Calculation failed: report output is missing.",
            "warnings": [*state.warnings, "calc_missing_report_output"],
        }

    try:
        base_metrics = map_report_response_to_base_metrics(run_response)
    except ValueError:
        return {
            "status": RunStatus.FAILED,
            "final_answer": "Calculation failed: unable to map report metrics.",
            "warnings": [*state.warnings, "calc_mapping_failed"],
        }

    report_id = state.selected_report_id or run_response.result.report_id
    calculation_specs = select_calculation_specs(report_id, state.intent, base_metrics)

    if not calculation_specs:
        return {
            "base_metrics": base_metrics,
            "derived_metrics": [],
            "calc_warnings": [],
            "warnings": [*state.warnings, "calc_no_formulas_selected"],
        }

    request = ComputeMetricsRequest(
        base_metrics=base_metrics,
        calculations=calculation_specs,
    )
    response = compute_metrics_tool(request)
    calc_warning_strings = [f"calc:{warning.value}" for warning in response.warnings]
    return {
        "base_metrics": base_metrics,
        "derived_metrics": response.derived_metrics,
        "calc_warnings": response.warnings,
        "warnings": [*state.warnings, *calc_warning_strings],
    }


def _clarify_node(state: AgentState) -> dict[str, Any]:
    question = state.clarification_question or (
        "Please clarify your request by providing a date range."
    )
    return {
        "status": RunStatus.CLARIFY,
        "final_answer": question,
        "needs_clarification": True,
        "clarification_question": question,
    }


def _reject_node(state: AgentState) -> dict[str, Any]:
    if state.user_scope is None or state.user_scope.status is AccessStatus.DENIED:
        return {
            "status": RunStatus.DENIED,
            "final_answer": "Access denied for this request.",
        }

    return {
        "status": RunStatus.REJECTED,
        "final_answer": (
            "Unsupported request. Supported reports: "
            "sales_total, order_count, average_check, sales_by_source."
        ),
    }


def _compose_answer_node(state: AgentState) -> dict[str, Any]:
    run_response = state.tool_responses.run_report
    if run_response is None:
        return {
            "status": RunStatus.FAILED,
            "final_answer": "Compose failed: report output is missing.",
            "warnings": [*state.warnings, "compose_missing_tool_output"],
        }

    metrics_text = ", ".join(
        f"{metric.label}={metric.value:.2f}" for metric in run_response.result.metrics
    )
    derived_text = ", ".join(
        (
            f"{metric.key}={metric.value:.2f}"
            if metric.value is not None
            else f"{metric.key}=n/a"
        )
        for metric in state.derived_metrics
    )
    derived_suffix = f" Derived metrics: {derived_text}." if derived_text else ""
    final_answer = (
        f"Report {run_response.result.report_id.value} "
        f"for {run_response.result.filters.date_from} to {run_response.result.filters.date_to}: "
        f"{metrics_text}.{derived_suffix}"
    )
    return {
        "status": RunStatus.COMPLETED,
        "final_answer": final_answer,
    }


def build_agent_graph() -> Any:
    """Build and compile the minimal Task 9 LangGraph workflow."""
    graph = StateGraph(AgentState)

    graph.add_node("resolve_scope", _resolve_scope_node)
    graph.add_node("interpret_request", _interpret_request_node)
    graph.add_node("route_decision", _route_decision_node)
    graph.add_node("run_report", _run_report_node)
    graph.add_node("calc_metrics", _calc_metrics_node)
    graph.add_node("clarify", _clarify_node)
    graph.add_node("reject", _reject_node)
    graph.add_node("compose_answer", _compose_answer_node)

    graph.set_entry_point("resolve_scope")
    graph.add_edge("resolve_scope", "interpret_request")
    graph.add_edge("interpret_request", "route_decision")
    graph.add_conditional_edges(
        "route_decision",
        _select_next_route,
        {
            "run_report": "run_report",
            "clarify": "clarify",
            "reject": "reject",
        },
    )
    graph.add_edge("run_report", "calc_metrics")
    graph.add_edge("calc_metrics", "compose_answer")
    graph.add_edge("compose_answer", END)
    graph.add_edge("clarify", END)
    graph.add_edge("reject", END)

    return graph.compile()
