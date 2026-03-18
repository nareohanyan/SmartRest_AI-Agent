"""Minimal LangGraph workflow for Task 9."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from langgraph.graph import END, StateGraph

from app.agent.calc_policy import select_calculation_specs
from app.agent.calc_tools import compute_metrics_tool
from app.agent.llm import (
    CLARIFICATION_FALLBACK_QUESTION,
    InterpretationContractError,
    LLMClientError,
    build_interpret_request_messages,
    get_llm_client,
    parse_interpretation_output_json,
    validate_interpretation_output,
)
from app.agent.metrics_mapper import map_report_response_to_base_metrics
from app.agent.report_tools import resolve_scope_tool, run_report_tool
from app.persistence.runtime_persistence import RuntimePersistenceService
from app.schemas.agent import AgentState, IntentType, LLMErrorCategory, RunStatus
from app.schemas.calculations import ComputeMetricsRequest
from app.schemas.reports import ReportFilters, ReportRequest, ReportType
from app.schemas.tools import AccessStatus, RunReportRequest

_DATE_RANGE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})")
_AUTHORIZATION_BLOCKED_WARNING = "authorization_blocked_report_not_allowed"
_INTERPRET_RATE_LIMIT_FALLBACK_WARNING = "interpretation_rate_limit_fallback"


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


def _generate_interpretation_payload(question: str) -> dict[str, Any]:
    selected_report_id = _detect_report_id(question)
    if selected_report_id is None:
        return {
            "intent": IntentType.UNSUPPORTED_REQUEST,
            "report_id": None,
            "filters": None,
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.3,
            "reasoning_notes": "No supported report matched the request text.",
        }

    filters = _extract_filters(question)
    if filters is None:
        return {
            "intent": IntentType.NEEDS_CLARIFICATION,
            "report_id": selected_report_id,
            "filters": None,
            "needs_clarification": True,
            "clarification_question": (
                "Please provide a date range using YYYY-MM-DD to YYYY-MM-DD."
            ),
            "confidence": 0.7,
            "reasoning_notes": "Report candidate detected but required date range is missing.",
        }

    intent = (
        IntentType.BREAKDOWN_KPI
        if selected_report_id is ReportType.SALES_BY_SOURCE
        else IntentType.GET_KPI
    )
    return {
        "intent": intent,
        "report_id": selected_report_id,
        "filters": filters,
        "needs_clarification": False,
        "clarification_question": None,
        "confidence": 0.9,
        "reasoning_notes": "Report and required filters were identified.",
    }


def _interpret_request_with_llm(
    question: str,
    llm_client: Any,
) -> dict[str, Any]:
    messages = build_interpret_request_messages(question)
    output_text = llm_client.generate_text(messages=messages)
    interpretation = parse_interpretation_output_json(output_text)
    return interpretation.model_dump(mode="python")


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


def _openai_interpret_node(state: AgentState) -> dict[str, Any]:
    warnings = [*state.warnings]
    try:
        try:
            llm_client = get_llm_client()
        except ValueError:
            raw_interpretation = _generate_interpretation_payload(state.user_question)
        else:
            try:
                raw_interpretation = _interpret_request_with_llm(state.user_question, llm_client)
            except LLMClientError as exc:
                if exc.category is not LLMErrorCategory.RATE_LIMIT:
                    raise
                raw_interpretation = _generate_interpretation_payload(state.user_question)
                warnings.append(_INTERPRET_RATE_LIMIT_FALLBACK_WARNING)

        interpretation = validate_interpretation_output(raw_interpretation)
    except InterpretationContractError:
        return {
            "intent": IntentType.NEEDS_CLARIFICATION,
            "selected_report_id": None,
            "filters": None,
            "needs_clarification": True,
            "clarification_question": CLARIFICATION_FALLBACK_QUESTION,
            "warnings": [*warnings, "interpretation_contract_invalid"],
        }

    return {
        "intent": interpretation.intent,
        "selected_report_id": interpretation.report_id,
        "filters": interpretation.filters,
        "needs_clarification": interpretation.needs_clarification,
        "clarification_question": interpretation.clarification_question,
        "warnings": warnings,
    }


def _authorize_report_node(state: AgentState) -> dict[str, Any]:
    if state.user_scope is None or state.user_scope.status is AccessStatus.DENIED:
        return {"status": RunStatus.DENIED}

    if state.needs_clarification or state.intent is IntentType.NEEDS_CLARIFICATION:
        question = state.clarification_question or CLARIFICATION_FALLBACK_QUESTION
        return {
            "status": RunStatus.CLARIFY,
            "needs_clarification": True,
            "clarification_question": question,
        }

    if state.intent is IntentType.UNSUPPORTED_REQUEST or state.selected_report_id is None:
        return {"status": RunStatus.REJECTED}

    if state.filters is None:
        return {
            "status": RunStatus.CLARIFY,
            "needs_clarification": True,
            "clarification_question": CLARIFICATION_FALLBACK_QUESTION,
        }

    if state.selected_report_id not in state.user_scope.allowed_report_ids:
        return {
            "status": RunStatus.DENIED,
            "warnings": [*state.warnings, _AUTHORIZATION_BLOCKED_WARNING],
        }

    return {"status": RunStatus.RUNNING}


def _select_authorization_route(state: AgentState) -> str:
    if state.status is RunStatus.DENIED:
        return "deny"
    if state.status is RunStatus.CLARIFY:
        return "clarify"
    if state.status is RunStatus.REJECTED:
        return "reject"
    if state.status is RunStatus.FAILED:
        return "fail"
    if state.status is RunStatus.RUNNING:
        return "run_report"
    return "fail"


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
    try:
        run_response = run_report_tool(run_request)
    except Exception:
        return {
            "status": RunStatus.FAILED,
            "final_answer": "Run failed: report execution error.",
            "warnings": [*state.warnings, "run_report_execution_failed"],
        }

    tool_responses = state.tool_responses.model_copy(deep=True)
    tool_responses.run_report = run_response
    return {
        "tool_responses": tool_responses,
        "warnings": [*state.warnings, *run_response.warnings],
    }


def _select_next_after_run_report(state: AgentState) -> str:
    if state.status is RunStatus.FAILED:
        return "fail"
    return "calc_metrics"


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


def _select_next_after_calc_metrics(state: AgentState) -> str:
    if state.status is RunStatus.FAILED:
        return "fail"
    return "reason_over_results"


def _reason_over_results_node(state: AgentState) -> dict[str, Any]:
    run_response = state.tool_responses.run_report
    if run_response is None:
        return {
            "status": RunStatus.FAILED,
            "final_answer": "Reasoning failed: report output is missing.",
            "warnings": [*state.warnings, "reason_missing_tool_output"],
        }
    return {}


def _select_next_after_reasoning(state: AgentState) -> str:
    if state.status is RunStatus.FAILED:
        return "fail"
    return "compose_output"


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
    return {
        "status": RunStatus.REJECTED,
        "final_answer": (
            "Unsupported request. Supported reports: "
            "sales_total, order_count, average_check, sales_by_source."
        ),
    }


def _deny_node(state: AgentState) -> dict[str, Any]:
    return {
        "status": RunStatus.DENIED,
        "final_answer": "Access denied for this request.",
    }


def _fail_node(state: AgentState) -> dict[str, Any]:
    if state.final_answer:
        return {"status": RunStatus.FAILED}
    return {
        "status": RunStatus.FAILED,
        "final_answer": "Run failed due to internal processing error.",
        "warnings": [*state.warnings, "runtime_failed"],
    }


def _compose_output_node(state: AgentState) -> dict[str, Any]:
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


def _select_next_after_compose(state: AgentState) -> str:
    if state.status is RunStatus.FAILED:
        return "fail"
    return "persist_run"


def build_agent_graph(
    *,
    persistence_service: RuntimePersistenceService | None = None,
) -> Any:
    """Build and compile the minimal Task 9 LangGraph workflow."""
    graph = StateGraph(AgentState)

    def _persist_run_node(state: AgentState) -> dict[str, Any]:
        if persistence_service is None:
            return {}

        finish_persistence_result = persistence_service.finish_run(
            thread_id=state.internal_thread_id,
            internal_run_id=state.internal_run_id,
            status=state.status,
            question=state.user_question,
            answer=state.final_answer,
            error_message=(
                state.final_answer
                if state.status is RunStatus.FAILED
                else None
            ),
        )
        return {
            "warnings": [*state.warnings, *finish_persistence_result.warnings],
            "run_persisted": True,
        }

    graph.add_node("resolve_scope", _resolve_scope_node)
    graph.add_node("openai_interpret", _openai_interpret_node)
    graph.add_node("authorize_report", _authorize_report_node)
    graph.add_node("run_report", _run_report_node)
    graph.add_node("calc_metrics", _calc_metrics_node)
    graph.add_node("reason_over_results", _reason_over_results_node)
    graph.add_node("clarify", _clarify_node)
    graph.add_node("reject", _reject_node)
    graph.add_node("deny", _deny_node)
    graph.add_node("fail", _fail_node)
    graph.add_node("compose_output", _compose_output_node)
    graph.add_node("persist_run", _persist_run_node)

    graph.set_entry_point("resolve_scope")
    graph.add_edge("resolve_scope", "openai_interpret")
    graph.add_edge("openai_interpret", "authorize_report")
    graph.add_conditional_edges(
        "authorize_report",
        _select_authorization_route,
        {
            "run_report": "run_report",
            "clarify": "clarify",
            "reject": "reject",
            "deny": "deny",
            "fail": "fail",
        },
    )
    graph.add_conditional_edges(
        "run_report",
        _select_next_after_run_report,
        {
            "calc_metrics": "calc_metrics",
            "fail": "fail",
        },
    )
    graph.add_conditional_edges(
        "calc_metrics",
        _select_next_after_calc_metrics,
        {
            "reason_over_results": "reason_over_results",
            "fail": "fail",
        },
    )
    graph.add_conditional_edges(
        "reason_over_results",
        _select_next_after_reasoning,
        {
            "compose_output": "compose_output",
            "fail": "fail",
        },
    )
    graph.add_conditional_edges(
        "compose_output",
        _select_next_after_compose,
        {
            "persist_run": "persist_run",
            "fail": "fail",
        },
    )
    graph.add_edge("clarify", "persist_run")
    graph.add_edge("reject", "persist_run")
    graph.add_edge("deny", "persist_run")
    graph.add_edge("fail", "persist_run")
    graph.add_edge("persist_run", END)

    return graph.compile()
