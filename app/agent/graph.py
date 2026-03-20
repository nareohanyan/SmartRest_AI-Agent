"""Hybrid planning LangGraph workflow."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from langgraph.graph import END, StateGraph

from app.agent.calc_policy import select_calculation_specs
from app.agent.llm import (
    LLMClientError,
    PlanningContractError,
    build_plan_messages,
    build_response_messages,
    get_llm_client,
    parse_plan_output_json,
)
from app.agent.metrics_mapper import map_report_response_to_base_metrics
from app.agent.planning import plan_analysis as deterministic_plan_analysis
from app.agent.planning_policy import evaluate_plan_policy
from app.agent.report_tools import resolve_scope_tool, run_report_tool
from app.agent.tools import (
    attach_breakdown_share_tool,
    bottom_k_tool,
    compute_scalar_metrics_tool,
    fetch_breakdown_tool,
    fetch_timeseries_tool,
    fetch_total_metric_tool,
    materialize_previous_period_metrics,
    moving_average_tool,
    top_k_tool,
    trend_slope_tool,
)
from app.core.config import get_settings
from app.schemas.agent import AgentState, IntentType, PlannerSource, PolicyRoute, RunStatus
from app.schemas.analysis import (
    AnalysisIntent,
    BreakdownRequest,
    DimensionName,
    MovingAverageRequest,
    RankItemsRequest,
    TimeseriesRequest,
    TotalMetricRequest,
    TrendSlopeRequest,
)
from app.schemas.calculations import ComputeMetricsRequest
from app.schemas.reports import ReportRequest
from app.schemas.tools import AccessStatus, RunReportRequest

_ARMENIAN_CHAR_RE = re.compile(r"[\u0531-\u058F]")


def _question_language(question: str) -> str:
    if _ARMENIAN_CHAR_RE.search(question) is not None:
        return "hy"
    return "en"


def _smalltalk_answer(language: str) -> str:
    if language == "hy":
        return "Ողջույն։ Ուրախ եմ տեսնել ձեզ այստեղ։"
    return "Hello. Nice to see you here."


def _safe_unsupported_answer(language: str) -> str:
    if language == "hy":
        return (
            "Ցավոք ես չունեմ բավականաչափ ինֆորմացիա տվյալ հարցին պատասխանելու համար։ Ավելին իմանալու համար կարող եք զանգահարել 060 44 55 66։ "
        )
    return (
        "Unfortunately i don't have enough information to answer your question. For further questions you can contact 060 44 55 66."
    )


def _access_denied_answer(language: str) -> str:
    if language == "hy":
        return "Մուտքը մերժված է այս հարցման համար։"
    return "Access denied for this request."


def _clarification_fallback_question(language: str) -> str:
    if language == "hy":
        return "Խնդրում եմ հստակեցրեք հարցումը:"
    return "Please clarify your request."


def _map_analysis_intent_to_runtime_intent(analysis_intent: AnalysisIntent) -> IntentType:
    if analysis_intent in {AnalysisIntent.BREAKDOWN, AnalysisIntent.RANKING}:
        return IntentType.BREAKDOWN_KPI
    if analysis_intent is AnalysisIntent.SMALLTALK:
        return IntentType.SMALLTALK
    if analysis_intent is AnalysisIntent.CLARIFY:
        return IntentType.NEEDS_CLARIFICATION
    if analysis_intent is AnalysisIntent.UNSUPPORTED:
        return IntentType.UNSUPPORTED_REQUEST
    return IntentType.GET_KPI


def _render_answer_with_llm(
    *,
    state: AgentState,
    route: str,
    fallback_answer: str,
) -> tuple[str, list[str]]:
    settings = get_settings()
    api_key = getattr(settings, "openai_api_key", None)
    if api_key is None or not str(api_key).strip():
        return fallback_answer, state.warnings

    try:
        llm_client = get_llm_client()
        messages = build_response_messages(
            {
                "route": route,
                "language_hint": _question_language(state.user_question),
                "user_question": state.user_question,
                "factual_answer": fallback_answer,
                "policy_reason": state.policy_reason,
                "warnings": state.warnings,
            }
        )
        rendered = llm_client.generate_text(messages=messages).strip()
        if not rendered:
            raise ValueError("LLM response rendering returned empty text.")
        return rendered, state.warnings
    except (LLMClientError, ValueError):
        return fallback_answer, [*state.warnings, "response_llm_fallback"]


def _merge_warnings(*warning_groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for warning_group in warning_groups:
        for warning in warning_group:
            if warning in seen:
                continue
            seen.add(warning)
            merged.append(warning)
    return merged


def _resolve_scope_node(state: AgentState) -> dict[str, Any]:
    if state.scope_request is None:
        return {
            "status": RunStatus.DENIED,
            "final_answer": "Access denied: missing scope request.",
            "warnings": [*state.warnings, "missing_scope_request"],
            "policy_route": PolicyRoute.REJECT,
            "policy_reason": "Scope request is missing.",
        }

    scope_response = resolve_scope_tool(state.scope_request)
    tool_responses = state.tool_responses.model_copy(deep=True)
    tool_responses.resolve_scope = scope_response
    return {"user_scope": scope_response, "tool_responses": tool_responses}


def _plan_analysis_with_llm(question: str) -> tuple[Any, float]:
    llm_client = get_llm_client()
    messages = build_plan_messages(question)
    output_text = llm_client.generate_text(messages=messages)
    envelope = parse_plan_output_json(output_text)
    return envelope.plan, envelope.confidence


def _plan_analysis_node(state: AgentState) -> dict[str, Any]:
    settings = get_settings()
    allow_fallback = settings.planner_mode != "llm" or settings.planner_fallback_enabled

    preplanned = deterministic_plan_analysis(state.user_question)
    if preplanned.intent is AnalysisIntent.SMALLTALK:
        return {
            "analysis_plan": preplanned,
            "plan_source": PlannerSource.DETERMINISTIC,
            "plan_confidence": None,
            "intent": _map_analysis_intent_to_runtime_intent(preplanned.intent),
            "needs_clarification": preplanned.needs_clarification,
            "clarification_question": preplanned.clarification_question,
            "warnings": state.warnings,
        }

    fallback_warning: str | None = None
    plan = None
    plan_source: PlannerSource
    plan_confidence: float | None = None

    if settings.planner_mode == "deterministic":
        plan = deterministic_plan_analysis(state.user_question)
        plan_source = PlannerSource.DETERMINISTIC
    else:
        try:
            plan, plan_confidence = _plan_analysis_with_llm(state.user_question)
            if plan_confidence < settings.planner_min_confidence:
                if not allow_fallback:
                    raise PlanningContractError("Planner confidence is below configured threshold.")
                fallback_warning = "planner_low_confidence_fallback"
                plan = deterministic_plan_analysis(state.user_question)
                plan_source = PlannerSource.FALLBACK
                plan_confidence = None
            else:
                plan_source = PlannerSource.LLM
        except (PlanningContractError, ValueError):
            if not allow_fallback:
                raise
            fallback_warning = "planner_contract_or_config_fallback"
            plan = deterministic_plan_analysis(state.user_question)
            plan_source = PlannerSource.FALLBACK
            plan_confidence = None
        except LLMClientError:
            if not allow_fallback:
                raise
            fallback_warning = "planner_llm_error_fallback"
            plan = deterministic_plan_analysis(state.user_question)
            plan_source = PlannerSource.FALLBACK
            plan_confidence = None

    warnings = state.warnings
    if fallback_warning is not None:
        warnings = [*warnings, fallback_warning]

    return {
        "analysis_plan": plan,
        "plan_source": plan_source,
        "plan_confidence": plan_confidence,
        "intent": _map_analysis_intent_to_runtime_intent(plan.intent),
        "needs_clarification": plan.needs_clarification,
        "clarification_question": plan.clarification_question,
        "warnings": warnings,
    }


def _policy_gate_node(state: AgentState) -> dict[str, Any]:
    plan = state.analysis_plan
    if plan is None:
        return {
            "policy_route": PolicyRoute.REJECT,
            "policy_reason": "Plan is missing.",
            "warnings": [*state.warnings, "policy:missing_plan"],
        }

    retrieval = plan.retrieval
    decision = evaluate_plan_policy(
        plan_intent=plan.intent,
        retrieval_mode=retrieval.mode if retrieval is not None else None,
        retrieval_metric=retrieval.metric if retrieval is not None else None,
        retrieval_dimension=retrieval.dimension if retrieval is not None else None,
        date_from=retrieval.date_from if retrieval is not None else None,
        date_to=retrieval.date_to if retrieval is not None else None,
        scope=state.user_scope,
        settings=get_settings(),
    )

    warnings = state.warnings
    if decision.reason_code != "ok":
        warnings = [*warnings, f"policy:{decision.reason_code}"]

    return {
        "policy_route": decision.route,
        "policy_reason": decision.reason_message,
        "selected_report_id": decision.mapped_report_id,
        "filters": decision.normalized_filters,
        "warnings": warnings,
    }


def _route_decision_node(state: AgentState) -> dict[str, Any]:
    return {}


def _select_next_route_from_policy(state: AgentState) -> str:
    if state.policy_route is None:
        return PolicyRoute.REJECT.value
    return state.policy_route.value


def _prepare_legacy_report_node(state: AgentState) -> dict[str, Any]:
    if state.selected_report_id is None or state.filters is None:
        return {
            "status": RunStatus.FAILED,
            "final_answer": "Run failed: policy did not provide report execution context.",
            "warnings": [*state.warnings, "policy_missing_report_context"],
        }
    return {}


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
    response = compute_scalar_metrics_tool(request)
    calc_warning_strings = [f"calc:{warning.value}" for warning in response.warnings]
    return {
        "base_metrics": base_metrics,
        "derived_metrics": response.derived_metrics,
        "calc_warnings": response.warnings,
        "warnings": [*state.warnings, *calc_warning_strings],
    }


def _run_comparison_node(state: AgentState) -> dict[str, Any]:
    plan = state.analysis_plan
    if plan is None or plan.retrieval is None or plan.previous_period_retrieval is None:
        return {
            "status": RunStatus.FAILED,
            "final_answer": "Comparison failed: missing period retrieval context.",
            "warnings": [*state.warnings, "comparison_missing_context"],
        }

    current = fetch_total_metric_tool(
        TotalMetricRequest(
            metric=plan.retrieval.metric,
            date_from=plan.retrieval.date_from,
            date_to=plan.retrieval.date_to,
        )
    )
    previous = fetch_total_metric_tool(
        TotalMetricRequest(
            metric=plan.previous_period_retrieval.metric,
            date_from=plan.previous_period_retrieval.date_from,
            date_to=plan.previous_period_retrieval.date_to,
        )
    )
    day_count = current.base_metrics.get("day_count", Decimal("0"))
    base_metrics = materialize_previous_period_metrics(
        current_metric_key=plan.retrieval.metric.value,
        current_total=current.value,
        previous_total=previous.value,
        day_count=day_count,
    )

    if plan.scalar_calculations:
        calc_response = compute_scalar_metrics_tool(
            ComputeMetricsRequest(
                base_metrics=base_metrics,
                calculations=plan.scalar_calculations,
            )
        )
        derived_metrics = calc_response.derived_metrics
        calc_warnings = calc_response.warnings
    else:
        derived_metrics = []
        calc_warnings = []

    summary = (
        f"Comparison for {plan.retrieval.metric.value} "
        f"({plan.retrieval.date_from} to {plan.retrieval.date_to}) vs previous period "
        f"({plan.previous_period_retrieval.date_from} "
        f"to {plan.previous_period_retrieval.date_to}): "
        f"current={current.value:.2f}, previous={previous.value:.2f}."
    )
    if derived_metrics:
        derived_summary = ", ".join(
            (
                f"{metric.key}={metric.value:.2f}"
                if metric.value is not None
                else f"{metric.key}=n/a"
            )
            for metric in derived_metrics
        )
        summary = f"{summary} Derived metrics: {derived_summary}."

    calc_warning_strings = [f"calc:{warning.value}" for warning in calc_warnings]
    return {
        "base_metrics": base_metrics,
        "derived_metrics": derived_metrics,
        "calc_warnings": calc_warnings,
        "analysis_artifacts": {
            **state.analysis_artifacts,
            "kind": "comparison",
            "summary": summary,
        },
        "warnings": _merge_warnings(
            state.warnings,
            current.warnings,
            previous.warnings,
            calc_warning_strings,
        ),
    }


def _run_ranking_node(state: AgentState) -> dict[str, Any]:
    plan = state.analysis_plan
    if plan is None or plan.retrieval is None:
        return {
            "status": RunStatus.FAILED,
            "final_answer": "Ranking failed: missing retrieval context.",
            "warnings": [*state.warnings, "ranking_missing_context"],
        }

    breakdown = fetch_breakdown_tool(
        BreakdownRequest(
            metric=plan.retrieval.metric,
            dimension=DimensionName.SOURCE,
            date_from=plan.retrieval.date_from,
            date_to=plan.retrieval.date_to,
        )
    )
    enriched = attach_breakdown_share_tool(breakdown)

    ranked_items = enriched.items
    if plan.ranking is not None:
        rank_request = RankItemsRequest(items=enriched.items, ranking=plan.ranking)
        if plan.ranking.mode.value == "top_k":
            ranked_items = top_k_tool(rank_request).items
        else:
            ranked_items = bottom_k_tool(rank_request).items

    summary_items = ", ".join(
        f"{item.label}={item.value:.2f}" for item in ranked_items
    )
    summary = (
        f"Ranking for {plan.retrieval.metric.value} by source "
        f"({plan.retrieval.date_from} to {plan.retrieval.date_to}): {summary_items}."
    )

    return {
        "analysis_artifacts": {
            **state.analysis_artifacts,
            "kind": "ranking",
            "summary": summary,
        },
        "warnings": [*state.warnings, *breakdown.warnings],
    }


def _run_trend_node(state: AgentState) -> dict[str, Any]:
    plan = state.analysis_plan
    if plan is None or plan.retrieval is None:
        return {
            "status": RunStatus.FAILED,
            "final_answer": "Trend failed: missing retrieval context.",
            "warnings": [*state.warnings, "trend_missing_context"],
        }

    timeseries = fetch_timeseries_tool(
        TimeseriesRequest(
            metric=plan.retrieval.metric,
            date_from=plan.retrieval.date_from,
            date_to=plan.retrieval.date_to,
            dimension=DimensionName.DAY,
        )
    )

    summary_parts = [
        (
            f"Trend for {plan.retrieval.metric.value} "
            f"({plan.retrieval.date_from} to {plan.retrieval.date_to})."
        )
    ]

    if plan.include_moving_average and len(timeseries.points) >= plan.moving_average_window:
        moving_average = moving_average_tool(
            MovingAverageRequest(
                points=timeseries.points,
                window_size=plan.moving_average_window,
            )
        )
        latest_ma = next(
            (point.value for point in reversed(moving_average.points) if point.value),
            None,
        )
        if latest_ma is not None:
            summary_parts.append(
                f"Latest {plan.moving_average_window}-day moving average: {latest_ma:.2f}."
            )

    if plan.include_trend_slope:
        if len(timeseries.points) >= 2:
            slope = trend_slope_tool(TrendSlopeRequest(points=timeseries.points))
            summary_parts.append(
                f"Slope per day: {slope.slope_per_day:.4f} ({slope.direction})."
            )
        else:
            summary_parts.append("Not enough points for slope calculation.")

    return {
        "analysis_artifacts": {
            **state.analysis_artifacts,
            "kind": "trend",
            "summary": " ".join(summary_parts),
        },
        "warnings": [*state.warnings, *timeseries.warnings],
    }


def _clarify_node(state: AgentState) -> dict[str, Any]:
    language = _question_language(state.user_question)
    fallback_question = state.clarification_question or (
        _clarification_fallback_question(language)
    )
    final_question, warnings = _render_answer_with_llm(
        state=state,
        route=PolicyRoute.CLARIFY.value,
        fallback_answer=fallback_question,
    )
    return {
        "status": RunStatus.CLARIFY,
        "final_answer": final_question,
        "needs_clarification": True,
        "clarification_question": final_question,
        "warnings": warnings,
    }


def _reject_node(state: AgentState) -> dict[str, Any]:
    language = _question_language(state.user_question)
    if state.user_scope is None or state.user_scope.status is AccessStatus.DENIED:
        fallback_answer = _access_denied_answer(language)
        final_answer, warnings = _render_answer_with_llm(
            state=state,
            route=PolicyRoute.REJECT.value,
            fallback_answer=fallback_answer,
        )
        return {
            "status": RunStatus.DENIED,
            "final_answer": final_answer,
            "warnings": warnings,
        }

    reason = state.policy_reason or (
        "Unsupported request." if language == "en" else "Չաջակցվող հարցում։"
    )
    supported_reports = (
        "Supported reports: sales_total, order_count, average_check, sales_by_source."
        if language == "en"
        else (
            "Աջակցվող հաշվետվություններն են՝ sales_total, order_count, "
            "average_check, sales_by_source։"
        )
    )
    fallback_answer = f"{reason} {supported_reports}"
    final_answer, warnings = _render_answer_with_llm(
        state=state,
        route=PolicyRoute.REJECT.value,
        fallback_answer=fallback_answer,
    )
    return {
        "status": RunStatus.REJECTED,
        "final_answer": final_answer,
        "warnings": warnings,
    }


def _safe_answer_node(state: AgentState) -> dict[str, Any]:
    language = _question_language(state.user_question)
    fallback_answer = _safe_unsupported_answer(language)
    final_answer, warnings = _render_answer_with_llm(
        state=state,
        route=PolicyRoute.SAFE_ANSWER.value,
        fallback_answer=fallback_answer,
    )
    return {
        "status": RunStatus.REJECTED,
        "final_answer": final_answer,
        "warnings": warnings,
    }


def _smalltalk_node(state: AgentState) -> dict[str, Any]:
    language = _question_language(state.user_question)
    final_answer = _smalltalk_answer(language)
    return {
        "status": RunStatus.ONBOARDING,
        "final_answer": final_answer,
        "needs_clarification": False,
        "clarification_question": None,
        "warnings": state.warnings,
    }


def _compose_answer_node(state: AgentState) -> dict[str, Any]:
    run_response = state.tool_responses.run_report
    if run_response is not None:
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
            f"for {run_response.result.filters.date_from} "
            f"to {run_response.result.filters.date_to}: "
            f"{metrics_text}.{derived_suffix}"
        )
        rendered_answer, warnings = _render_answer_with_llm(
            state=state,
            route=RunStatus.COMPLETED.value,
            fallback_answer=final_answer,
        )
        return {
            "status": RunStatus.COMPLETED,
            "final_answer": rendered_answer,
            "warnings": warnings,
        }

    summary = state.analysis_artifacts.get("summary")
    if isinstance(summary, str) and summary.strip():
        rendered_answer, warnings = _render_answer_with_llm(
            state=state,
            route=RunStatus.COMPLETED.value,
            fallback_answer=summary,
        )
        return {
            "status": RunStatus.COMPLETED,
            "final_answer": rendered_answer,
            "warnings": warnings,
        }

    return {
        "status": RunStatus.FAILED,
        "final_answer": "Compose failed: no supported output artifacts were produced.",
        "warnings": [*state.warnings, "compose_missing_tool_output"],
    }


def build_agent_graph() -> Any:
    """Build and compile hybrid planning workflow."""
    graph = StateGraph(AgentState)

    graph.add_node("resolve_scope", _resolve_scope_node)
    graph.add_node("plan_analysis", _plan_analysis_node)
    graph.add_node("policy_gate", _policy_gate_node)
    graph.add_node("route_decision", _route_decision_node)
    graph.add_node("prepare_legacy_report", _prepare_legacy_report_node)
    graph.add_node("run_report", _run_report_node)
    graph.add_node("calc_metrics", _calc_metrics_node)
    graph.add_node("run_comparison", _run_comparison_node)
    graph.add_node("run_ranking", _run_ranking_node)
    graph.add_node("run_trend", _run_trend_node)
    graph.add_node("smalltalk", _smalltalk_node)
    graph.add_node("clarify", _clarify_node)
    graph.add_node("reject", _reject_node)
    graph.add_node("safe_answer", _safe_answer_node)
    graph.add_node("compose_answer", _compose_answer_node)

    graph.set_entry_point("resolve_scope")
    graph.add_edge("resolve_scope", "plan_analysis")
    graph.add_edge("plan_analysis", "policy_gate")
    graph.add_edge("policy_gate", "route_decision")
    graph.add_conditional_edges(
        "route_decision",
        _select_next_route_from_policy,
        {
            PolicyRoute.PREPARE_LEGACY_REPORT.value: "prepare_legacy_report",
            PolicyRoute.RUN_COMPARISON.value: "run_comparison",
            PolicyRoute.RUN_RANKING.value: "run_ranking",
            PolicyRoute.RUN_TREND.value: "run_trend",
            PolicyRoute.SMALLTALK.value: "smalltalk",
            PolicyRoute.CLARIFY.value: "clarify",
            PolicyRoute.REJECT.value: "reject",
            PolicyRoute.SAFE_ANSWER.value: "safe_answer",
        },
    )
    graph.add_edge("prepare_legacy_report", "run_report")
    graph.add_edge("run_report", "calc_metrics")
    graph.add_edge("calc_metrics", "compose_answer")
    graph.add_edge("run_comparison", "compose_answer")
    graph.add_edge("run_ranking", "compose_answer")
    graph.add_edge("run_trend", "compose_answer")
    graph.add_edge("compose_answer", END)
    graph.add_edge("smalltalk", END)
    graph.add_edge("clarify", END)
    graph.add_edge("reject", END)
    graph.add_edge("safe_answer", END)

    return graph.compile()
