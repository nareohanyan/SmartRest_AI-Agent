"""Hybrid planning LangGraph workflow."""

from __future__ import annotations

import re
from decimal import Decimal
from time import perf_counter
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
from app.agent.planning import (
    plan_analysis as deterministic_plan_analysis,
)
from app.agent.planning import (
    plan_legacy_tasks,
)
from app.agent.planning_policy import evaluate_business_query_policy, evaluate_plan_policy
from app.agent.tool_registry import ToolId, get_tool_registry
from app.agent.tools.analytics import materialize_previous_period_metrics
from app.core.config import get_settings
from app.schemas.agent import (
    AgentState,
    ExecutionStepStatus,
    ExecutionTraceStep,
    IntentType,
    PlannerSource,
    PolicyRoute,
    RunStatus,
)
from app.schemas.analysis import (
    AnalysisIntent,
    BreakdownRequest,
    BusinessQueryKind,
    BusinessQuerySpec,
    CustomerSummaryRequest,
    DimensionName,
    ItemPerformanceMetric,
    ItemPerformanceRequest,
    ItemPerformanceResponse,
    LegacyReportTask,
    LegacyReportTaskResult,
    MovingAverageRequest,
    RankingMode,
    RankItemsRequest,
    ReceiptSummaryRequest,
    RetrievalScope,
    TimeseriesRequest,
    ToolWarningCode,
    TotalMetricRequest,
    TrendSlopeRequest,
)
from app.schemas.calculations import ComputeMetricsRequest
from app.schemas.reports import ReportFilters, ReportRequest, ReportType
from app.schemas.tools import AccessStatus, RunReportRequest, ToolOperation

_ARMENIAN_CHAR_RE = re.compile(r"[\u0531-\u058F]")
_CYRILLIC_CHAR_RE = re.compile(r"[\u0400-\u04FF]")


def _question_language(question: str) -> str:
    if _ARMENIAN_CHAR_RE.search(question) is not None:
        return "hy"
    if _CYRILLIC_CHAR_RE.search(question) is not None:
        return "ru"
    return "en"


def _smalltalk_answer(language: str) -> str:
    if language == "hy":
        return "Ողջու՜յն։ Ինչո՞վ կարող եմ օգնել ձեզ այսօր։"
    if language == "ru":
        return "Здравствуйте. Чем я могу вам сегодня помочь?"
    return "Hello. Nice to see you here."


def _item_metric_label(metric: ItemPerformanceMetric, language: str) -> str:
    if metric is ItemPerformanceMetric.QUANTITY_SOLD:
        return (
            "ամենավաճառված ապրանքները"
            if language == "hy"
            else (
                "самые продаваемые товары"
                if language == "ru"
                else "top selling items"
            )
        )
    if metric is ItemPerformanceMetric.DISTINCT_ORDERS:
        return (
            "ամենաշատ պատվիրված ապրանքները"
            if language == "hy"
            else (
                "самые часто заказываемые товары"
                if language == "ru"
                else "most frequently ordered items"
            )
        )
    return (
        "ամենաեկամտաբեր ապրանքները"
        if language == "hy"
        else (
            "самые доходные товары"
            if language == "ru"
            else "highest revenue items"
        )
    )


def _format_item_value(
    *,
    metric: ItemPerformanceMetric,
    value: Decimal,
    language: str,
) -> str:
    if metric is ItemPerformanceMetric.QUANTITY_SOLD:
        quantized = int(value) if value == value.to_integral_value() else f"{value:.2f}"
        suffix = " հատ" if language == "hy" else (" шт." if language == "ru" else " units")
        return f"{quantized}{suffix}"
    if metric is ItemPerformanceMetric.DISTINCT_ORDERS:
        quantized = int(value) if value == value.to_integral_value() else f"{value:.2f}"
        suffix = (
            " պատվեր" if language == "hy" else (" заказов" if language == "ru" else " orders")
        )
        return f"{quantized}{suffix}"
    suffix = " դրամ" if language == "hy" else (" драм" if language == "ru" else "")
    return f"{value:.2f}{suffix}"


def _build_item_performance_summary(
    *,
    business_query: BusinessQuerySpec,
    response: ItemPerformanceResponse,
    language: str,
) -> str:
    if not response.items:
        return (
            (
                f"{business_query.date_from}-ից մինչև "
                f"{business_query.date_to} տվյալներով ապրանքներ չեն գտնվել։"
            )
            if language == "hy"
            else (
                (
                    f"За период с {business_query.date_from} по "
                    f"{business_query.date_to} товары не найдены."
                )
                if language == "ru"
                else (
                    f"No items were found from {business_query.date_from} "
                    f"to {business_query.date_to}."
                )
            )
        )

    ranking_label = (
        "տոփ" if business_query.ranking_mode is RankingMode.TOP_K else "վերջին"
        if language == "hy"
        else (
            "топ" if business_query.ranking_mode is RankingMode.TOP_K else "последние"
            if language == "ru"
            else "top" if business_query.ranking_mode is RankingMode.TOP_K else "bottom"
        )
    )
    metric_label = _item_metric_label(response.metric, language)
    if language == "hy":
        header = (
            f"Ահա {business_query.date_from}-ից մինչև {business_query.date_to} "
            f"{ranking_label} {len(response.items)} {metric_label}։"
        )
    elif language == "ru":
        header = (
            f"Вот {ranking_label} {len(response.items)} {metric_label} "
            f"за период с {business_query.date_from} по {business_query.date_to}."
        )
    else:
        header = (
            f"Here are the {ranking_label} {len(response.items)} {metric_label} "
            f"from {business_query.date_from} to {business_query.date_to}."
        )

    lines = [
        f"{index}. {item.name} — "
        f"{_format_item_value(metric=response.metric, value=item.value, language=language)}"
        for index, item in enumerate(response.items, start=1)
    ]
    return "\n".join([header, *lines])


def _safe_unsupported_answer(language: str) -> str:
    if language == "hy":
        return (
            "Ցավոք ես չունեմ բավականաչափ ինֆորմացիա տվյալ հարցին պատասխանելու համար։ "
            "Ավելին իմանալու համար կարող եք զանգահարել 060 44 55 66։ "
        )
    if language == "ru":
        return (
            "К сожалению, у меня недостаточно информации, чтобы ответить на этот вопрос. "
            "Для получения дополнительной информации вы можете позвонить по номеру 060 44 55 66."
        )
    return (
        "Unfortunately i don't have enough information to answer your question. "
        "For further questions you can contact 060 44 55 66."
    )


def _access_denied_answer(language: str) -> str:
    if language == "hy":
        return "Մուտքը մերժված է այս հարցման համար։"
    if language == "ru":
        return "Доступ по данному запросу запрещен."
    return "Access denied for this request."


def _clarification_fallback_question(language: str) -> str:
    if language == "hy":
        return "Խնդրում եմ հստակեցրեք հարցումը:"
    if language == "ru":
        return "Пожалуйста, уточните запрос."
    return "Please clarify your request."


def _parse_branch_id(raw_branch_id: str) -> int | None:
    normalized = raw_branch_id.strip()
    if normalized.startswith("branch_"):
        normalized = normalized[len("branch_") :]
    try:
        return int(normalized)
    except ValueError:
        return None


def _normalize_branch_ids(raw_branch_ids: list[str] | None) -> list[int]:
    if not raw_branch_ids:
        return []

    branch_ids: list[int] = []
    seen: set[int] = set()
    for raw_branch_id in raw_branch_ids:
        parsed = _parse_branch_id(raw_branch_id)
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        branch_ids.append(parsed)
    return branch_ids


def _scoped_branch_ids(state: AgentState) -> list[int]:
    requested_branch_ids = (
        state.scope_request.requested_branch_ids
        if state.scope_request is not None
        else None
    )
    if requested_branch_ids:
        return _normalize_branch_ids(requested_branch_ids)

    scope = state.user_scope
    if scope is None:
        return []

    allowed_branch_ids = scope.allowed_branch_ids or []
    if "*" in allowed_branch_ids:
        return []
    return _normalize_branch_ids(allowed_branch_ids)


def _build_retrieval_scope(state: AgentState) -> RetrievalScope | None:
    if state.scope_request is None:
        return None

    source = None
    if state.filters is not None:
        source = state.filters.source

    return RetrievalScope(
        profile_id=state.scope_request.profile_id,
        branch_ids=_scoped_branch_ids(state),
        source=source,
    )


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


def _stringify_tool_warnings(warnings: list[ToolWarningCode]) -> list[str]:
    return [f"tool:{warning.value}" for warning in warnings]


def _append_tool_trace_step(
    trace: list[ExecutionTraceStep],
    *,
    step_id: str,
    input_ref: str,
    output_ref: str,
    started_at: float,
    status: ExecutionStepStatus = ExecutionStepStatus.SUCCESS,
    warnings: list[str] | None = None,
    error_code: str | None = None,
) -> list[ExecutionTraceStep]:
    return [
        *trace,
        ExecutionTraceStep(
            step_id=step_id,
            status=status,
            input_ref=input_ref,
            output_ref=output_ref,
            duration_ms=(perf_counter() - started_at) * 1000,
            warnings=warnings or [],
            error_code=error_code,
        ),
    ]


def _resolve_scope_node(state: AgentState) -> dict[str, Any]:
    if state.scope_request is None:
        started_at = perf_counter()
        execution_trace = _append_tool_trace_step(
            state.execution_trace,
            step_id="tool.resolve_scope",
            input_ref="scope_request",
            output_ref="user_scope",
            started_at=started_at,
            status=ExecutionStepStatus.FAILED,
            warnings=["missing_scope_request"],
            error_code="missing_scope_request",
        )
        return {
            "status": RunStatus.DENIED,
            "final_answer": "Access denied: missing scope request.",
            "warnings": [*state.warnings, "missing_scope_request"],
            "policy_route": PolicyRoute.REJECT,
            "policy_reason": "Scope request is missing.",
            "execution_trace": execution_trace,
        }

    started_at = perf_counter()
    scope_response = get_tool_registry().invoke(ToolId.RESOLVE_SCOPE, state.scope_request)
    execution_trace = _append_tool_trace_step(
        state.execution_trace,
        step_id="tool.resolve_scope",
        input_ref="scope_request",
        output_ref="user_scope",
        started_at=started_at,
    )
    tool_responses = state.tool_responses.model_copy(deep=True)
    tool_responses.resolve_scope = scope_response
    return {
        "user_scope": scope_response,
        "tool_responses": tool_responses,
        "execution_trace": execution_trace,
    }


def _plan_analysis_with_llm(question: str) -> tuple[Any, float]:
    llm_client = get_llm_client()
    messages = build_plan_messages(question)
    output_text = llm_client.generate_text(messages=messages)
    envelope = parse_plan_output_json(output_text)
    return envelope.plan, envelope.confidence


def _plan_analysis_node(state: AgentState) -> dict[str, Any]:
    settings = get_settings()
    allow_fallback = settings.planner_mode != "llm" or settings.planner_fallback_enabled

    planned_tasks = plan_legacy_tasks(state.user_question)
    if planned_tasks is not None:
        return {
            "legacy_tasks": planned_tasks,
            "analysis_plan": None,
            "plan_source": PlannerSource.DETERMINISTIC,
            "plan_confidence": None,
            "intent": IntentType.GET_KPI,
            "needs_clarification": False,
            "clarification_question": None,
            "warnings": state.warnings,
        }

    preplanned = deterministic_plan_analysis(state.user_question)
    if preplanned.intent is AnalysisIntent.SMALLTALK or preplanned.business_query is not None:
        return {
            "analysis_plan": preplanned,
            "legacy_tasks": [],
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
        "legacy_tasks": [],
        "plan_source": plan_source,
        "plan_confidence": plan_confidence,
        "intent": _map_analysis_intent_to_runtime_intent(plan.intent),
        "needs_clarification": plan.needs_clarification,
        "clarification_question": plan.clarification_question,
        "warnings": warnings,
    }


def _policy_gate_node(state: AgentState) -> dict[str, Any]:
    if state.legacy_tasks:
        if state.user_scope is None:
            return {
                "policy_route": PolicyRoute.REJECT,
                "policy_reason": "Scope is missing.",
                "warnings": [*state.warnings, "policy:missing_scope"],
            }

        if state.user_scope.status is AccessStatus.DENIED:
            return {
                "policy_route": PolicyRoute.REJECT,
                "policy_reason": state.user_scope.denial_reason or "Access denied.",
                "warnings": [*state.warnings, "policy:access_denied"],
            }

        unsupported_tasks = [
            task for task in state.legacy_tasks if not task.supported or task.report_id is None
        ]
        blocked_report = next(
            (
                task.report_id
                for task in state.legacy_tasks
                if task.supported
                and task.report_id is not None
                and task.report_id not in state.user_scope.allowed_report_ids
            ),
            None,
        )
        if blocked_report is not None:
            return {
                "policy_route": PolicyRoute.REJECT,
                "policy_reason": f"Report {blocked_report.value} is not allowed for this scope.",
                "warnings": [*state.warnings, "policy:report_not_allowed"],
            }

        warnings = state.warnings
        if unsupported_tasks:
            warnings = [*warnings, "planner_partial_multi_task"]

        return {
            "policy_route": PolicyRoute.RUN_MULTI_REPORT,
            "policy_reason": "Compound KPI request routed to multi-report execution.",
            "warnings": warnings,
        }

    plan = state.analysis_plan
    if plan is None:
        return {
            "policy_route": PolicyRoute.REJECT,
            "policy_reason": "Plan is missing.",
            "warnings": [*state.warnings, "policy:missing_plan"],
        }

    if plan.business_query is not None:
        required_tool = {
            BusinessQueryKind.ITEM_PERFORMANCE: ToolOperation.FETCH_ITEM_PERFORMANCE,
            BusinessQueryKind.CUSTOMER_SUMMARY: ToolOperation.FETCH_CUSTOMER_SUMMARY,
            BusinessQueryKind.RECEIPT_SUMMARY: ToolOperation.FETCH_RECEIPT_SUMMARY,
        }[plan.business_query.kind]
        decision = evaluate_business_query_policy(
            date_from=plan.business_query.date_from,
            date_to=plan.business_query.date_to,
            scope=state.user_scope,
            settings=get_settings(),
            required_tool=required_tool,
            requested_branch_ids=(
                state.scope_request.requested_branch_ids
                if state.scope_request is not None
                else None
            ),
            requested_export_mode=(
                state.scope_request.requested_export_mode
                if state.scope_request is not None
                else None
            ),
        )
        warnings = state.warnings
        if decision.reason_code != "ok":
            warnings = [*warnings, f"policy:{decision.reason_code}"]
        return {
            "policy_route": decision.route,
            "policy_reason": decision.reason_message,
            "warnings": warnings,
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
        compare_to_previous_period=plan.compare_to_previous_period,
        previous_period_metric=(
            plan.previous_period_retrieval.metric
            if plan.previous_period_retrieval is not None
            else None
        ),
        ranking_mode=plan.ranking.mode if plan.ranking is not None else None,
        include_moving_average=plan.include_moving_average,
        include_trend_slope=plan.include_trend_slope,
        has_scalar_calculations=bool(plan.scalar_calculations),
        requested_branch_ids=(
            state.scope_request.requested_branch_ids
            if state.scope_request is not None
            else None
        ),
        requested_export_mode=(
            state.scope_request.requested_export_mode
            if state.scope_request is not None
            else None
        ),
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
        started_at = perf_counter()
        execution_trace = _append_tool_trace_step(
            state.execution_trace,
            step_id="tool.run_report",
            input_ref="run_report_request",
            output_ref="run_report_response",
            started_at=started_at,
            status=ExecutionStepStatus.FAILED,
            warnings=["run_report_missing_context"],
            error_code="run_report_missing_context",
        )
        return {
            "status": RunStatus.FAILED,
            "final_answer": "Run failed: missing required report execution context.",
            "warnings": [*state.warnings, "run_report_missing_context"],
            "execution_trace": execution_trace,
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
    started_at = perf_counter()
    run_response = get_tool_registry().invoke(ToolId.RUN_REPORT, run_request)
    execution_trace = _append_tool_trace_step(
        state.execution_trace,
        step_id="tool.run_report",
        input_ref="run_report_request",
        output_ref="run_report_response",
        started_at=started_at,
        warnings=run_response.warnings,
    )

    tool_responses = state.tool_responses.model_copy(deep=True)
    tool_responses.run_report = run_response
    return {
        "tool_responses": tool_responses,
        "warnings": [*state.warnings, *run_response.warnings],
        "execution_trace": execution_trace,
    }


def _format_metric_value(value: float) -> str:
    return f"{value:.2f}"


def _build_legacy_task_fragment(
    *,
    task: LegacyReportTask,
    run_response: Any,
    derived_metrics: dict[str, Decimal],
) -> str:
    report_id = run_response.result.report_id
    date_from = run_response.result.filters.date_from
    date_to = run_response.result.filters.date_to
    metrics = {metric.label: metric.value for metric in run_response.result.metrics}

    if report_id is ReportType.SALES_TOTAL:
        sales_total = metrics.get("sales_total")
        per_day = derived_metrics.get("sales_total_per_day")
        if sales_total is not None:
            fragment = (
                f"Total sales from {date_from} to {date_to} were "
                f"{_format_metric_value(sales_total)}."
            )
            if per_day is not None:
                fragment = (
                    f"{fragment} Average per day was {per_day:.2f}."
                )
            return fragment

    if report_id is ReportType.ORDER_COUNT:
        order_count = metrics.get("order_count")
        per_day = derived_metrics.get("order_count_per_day")
        if order_count is not None:
            fragment = (
                f"Order count from {date_from} to {date_to} was "
                f"{_format_metric_value(order_count)}."
            )
            if per_day is not None:
                fragment = f"{fragment} Average per day was {per_day:.2f}."
            return fragment

    if report_id is ReportType.AVERAGE_CHECK:
        average_check = metrics.get("average_check")
        if average_check is not None:
            return (
                f"Average check from {date_from} to {date_to} was "
                f"{_format_metric_value(average_check)}."
            )

    metrics_text = ", ".join(
        f"{metric.label}={metric.value:.2f}" for metric in run_response.result.metrics
    )
    return f"Report {report_id.value} for {date_from} to {date_to}: {metrics_text}."


def _build_unsupported_task_fragment(task: LegacyReportTask) -> str:
    return f"I couldn't answer '{task.user_subquery}' because that metric is not supported yet."


def _run_multi_report_node(state: AgentState) -> dict[str, Any]:
    if state.scope_request is None:
        return {
            "status": RunStatus.FAILED,
            "final_answer": "Run failed: missing required report execution context.",
            "warnings": [*state.warnings, "run_multi_report_missing_context"],
        }

    warnings = list(state.warnings)
    execution_trace = list(state.execution_trace)
    task_results: list[LegacyReportTaskResult] = []
    summary_parts: list[str] = []

    for task in state.legacy_tasks:
        if (
            not task.supported
            or task.report_id is None
            or task.date_from is None
            or task.date_to is None
        ):
            fragment = _build_unsupported_task_fragment(task)
            task_results.append(
                LegacyReportTaskResult(
                    task_id=task.task_id,
                    status="unsupported",
                    answer_fragment=fragment,
                )
            )
            summary_parts.append(fragment)
            continue

        run_request = RunReportRequest(
            user_id=state.scope_request.user_id,
            profile_id=state.scope_request.profile_id,
            profile_nick=state.scope_request.profile_nick,
            request=ReportRequest(
                report_id=task.report_id,
                filters=ReportFilters(
                    date_from=task.date_from,
                    date_to=task.date_to,
                ),
            ),
        )
        started_at = perf_counter()
        run_response = get_tool_registry().invoke(ToolId.RUN_REPORT, run_request)
        execution_trace = _append_tool_trace_step(
            execution_trace,
            step_id=f"tool.run_report.{task.task_id}",
            input_ref=f"legacy_tasks.{task.task_id}",
            output_ref=f"run_report_response.{task.task_id}",
            started_at=started_at,
            warnings=run_response.warnings,
        )
        warnings = [*warnings, *run_response.warnings]

        derived_metric_values: dict[str, Decimal] = {}
        try:
            base_metrics = map_report_response_to_base_metrics(run_response)
            calc_specs = select_calculation_specs(task.report_id, state.intent, base_metrics)
        except ValueError:
            base_metrics = {}
            calc_specs = []

        if calc_specs:
            calc_started_at = perf_counter()
            calc_response = get_tool_registry().invoke(
                ToolId.COMPUTE_SCALAR_METRICS,
                ComputeMetricsRequest(
                    base_metrics=base_metrics,
                    calculations=calc_specs,
                ),
            )
            execution_trace = _append_tool_trace_step(
                execution_trace,
                step_id=f"tool.compute_scalar_metrics.{task.task_id}",
                input_ref=f"legacy_tasks.{task.task_id}",
                output_ref=f"compute_metrics_response.{task.task_id}",
                started_at=calc_started_at,
            )
            calc_warning_strings = [f"calc:{warning.value}" for warning in calc_response.warnings]
            warnings = [*warnings, *calc_warning_strings]
            derived_metric_values = {
                metric.key: metric.value
                for metric in calc_response.derived_metrics
                if metric.value is not None
            }

        fragment = _build_legacy_task_fragment(
            task=task,
            run_response=run_response,
            derived_metrics=derived_metric_values,
        )
        task_results.append(
            LegacyReportTaskResult(
                task_id=task.task_id,
                status="completed",
                answer_fragment=fragment,
                warnings=run_response.warnings,
            )
        )
        summary_parts.append(fragment)

    if not any(result.status == "completed" for result in task_results):
        return {
            "status": RunStatus.FAILED,
            "final_answer": "Run failed: no supported multi-report tasks were executed.",
            "warnings": [*warnings, "run_multi_report_no_supported_tasks"],
            "execution_trace": execution_trace,
        }

    return {
        "legacy_task_results": task_results,
        "analysis_artifacts": {
            **state.analysis_artifacts,
            "kind": "multi_report",
            "summary": " ".join(summary_parts),
        },
        "warnings": warnings,
        "execution_trace": execution_trace,
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
    started_at = perf_counter()
    response = get_tool_registry().invoke(ToolId.COMPUTE_SCALAR_METRICS, request)
    execution_trace = _append_tool_trace_step(
        state.execution_trace,
        step_id="tool.compute_scalar_metrics",
        input_ref="compute_metrics_request",
        output_ref="compute_metrics_response",
        started_at=started_at,
    )
    calc_warning_strings = [f"calc:{warning.value}" for warning in response.warnings]
    return {
        "base_metrics": base_metrics,
        "derived_metrics": response.derived_metrics,
        "calc_warnings": response.warnings,
        "warnings": [*state.warnings, *calc_warning_strings],
        "execution_trace": execution_trace,
    }


def _run_comparison_node(state: AgentState) -> dict[str, Any]:
    plan = state.analysis_plan
    if plan is None or plan.retrieval is None or plan.previous_period_retrieval is None:
        return {
            "status": RunStatus.FAILED,
            "final_answer": "Comparison failed: missing period retrieval context.",
            "warnings": [*state.warnings, "comparison_missing_context"],
        }

    tool_registry = get_tool_registry()
    execution_trace = state.execution_trace
    retrieval_scope = _build_retrieval_scope(state)

    current_request = TotalMetricRequest(
        metric=plan.retrieval.metric,
        date_from=plan.retrieval.date_from,
        date_to=plan.retrieval.date_to,
        scope=retrieval_scope,
    )
    current_started_at = perf_counter()
    current = tool_registry.invoke(ToolId.FETCH_TOTAL_METRIC, current_request)
    execution_trace = _append_tool_trace_step(
        execution_trace,
        step_id="tool.fetch_total_metric.current",
        input_ref="analysis_plan.retrieval",
        output_ref="total_metric.current",
        started_at=current_started_at,
        warnings=_stringify_tool_warnings(current.warnings),
    )

    previous_request = TotalMetricRequest(
        metric=plan.previous_period_retrieval.metric,
        date_from=plan.previous_period_retrieval.date_from,
        date_to=plan.previous_period_retrieval.date_to,
        scope=retrieval_scope,
    )
    previous_started_at = perf_counter()
    previous = tool_registry.invoke(ToolId.FETCH_TOTAL_METRIC, previous_request)
    execution_trace = _append_tool_trace_step(
        execution_trace,
        step_id="tool.fetch_total_metric.previous",
        input_ref="analysis_plan.previous_period_retrieval",
        output_ref="total_metric.previous",
        started_at=previous_started_at,
        warnings=_stringify_tool_warnings(previous.warnings),
    )
    day_count = current.base_metrics.get("day_count", Decimal("0"))
    base_metrics = materialize_previous_period_metrics(
        current_metric_key=plan.retrieval.metric.value,
        current_total=current.value,
        previous_total=previous.value,
        day_count=day_count,
    )

    if plan.scalar_calculations:
        calc_request = ComputeMetricsRequest(
            base_metrics=base_metrics,
            calculations=plan.scalar_calculations,
        )
        calc_started_at = perf_counter()
        calc_response = tool_registry.invoke(ToolId.COMPUTE_SCALAR_METRICS, calc_request)
        execution_trace = _append_tool_trace_step(
            execution_trace,
            step_id="tool.compute_scalar_metrics.comparison",
            input_ref="comparison.base_metrics",
            output_ref="comparison.derived_metrics",
            started_at=calc_started_at,
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
            _stringify_tool_warnings(current.warnings),
            _stringify_tool_warnings(previous.warnings),
            calc_warning_strings,
        ),
        "execution_trace": execution_trace,
    }


def _run_total_node(state: AgentState) -> dict[str, Any]:
    plan = state.analysis_plan
    if plan is None or plan.retrieval is None:
        return {
            "status": RunStatus.FAILED,
            "final_answer": "Total metric retrieval failed: missing retrieval context.",
            "warnings": [*state.warnings, "total_missing_context"],
        }

    tool_registry = get_tool_registry()
    retrieval_scope = _build_retrieval_scope(state)

    request = TotalMetricRequest(
        metric=plan.retrieval.metric,
        date_from=plan.retrieval.date_from,
        date_to=plan.retrieval.date_to,
        scope=retrieval_scope,
    )
    started_at = perf_counter()
    response = tool_registry.invoke(ToolId.FETCH_TOTAL_METRIC, request)
    execution_trace = _append_tool_trace_step(
        state.execution_trace,
        step_id="tool.fetch_total_metric.current",
        input_ref="analysis_plan.retrieval",
        output_ref="total_metric.current",
        started_at=started_at,
        warnings=_stringify_tool_warnings(response.warnings),
    )

    base_metrics = dict(response.base_metrics)
    if plan.scalar_calculations:
        calc_request = ComputeMetricsRequest(
            base_metrics=base_metrics,
            calculations=plan.scalar_calculations,
        )
        calc_started_at = perf_counter()
        calc_response = tool_registry.invoke(ToolId.COMPUTE_SCALAR_METRICS, calc_request)
        execution_trace = _append_tool_trace_step(
            execution_trace,
            step_id="tool.compute_scalar_metrics.total",
            input_ref="total_metric.base_metrics",
            output_ref="total_metric.derived_metrics",
            started_at=calc_started_at,
        )
        derived_metrics = calc_response.derived_metrics
        calc_warnings = calc_response.warnings
    else:
        derived_metrics = []
        calc_warnings = []

    summary = (
        f"Total for {plan.retrieval.metric.value} "
        f"({plan.retrieval.date_from} to {plan.retrieval.date_to}): "
        f"value={response.value:.2f}."
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
            "kind": "total",
            "summary": summary,
        },
        "warnings": _merge_warnings(
            state.warnings,
            _stringify_tool_warnings(response.warnings),
            calc_warning_strings,
        ),
        "execution_trace": execution_trace,
    }


def _run_ranking_node(state: AgentState) -> dict[str, Any]:
    plan = state.analysis_plan
    if plan is None or plan.retrieval is None:
        return {
            "status": RunStatus.FAILED,
            "final_answer": "Breakdown failed: missing retrieval context.",
            "warnings": [*state.warnings, "breakdown_missing_context"],
        }

    tool_registry = get_tool_registry()
    execution_trace = state.execution_trace
    requested_dimension = plan.retrieval.dimension or DimensionName.SOURCE
    retrieval_scope = _build_retrieval_scope(state)

    breakdown_request = BreakdownRequest(
        metric=plan.retrieval.metric,
        dimension=requested_dimension,
        date_from=plan.retrieval.date_from,
        date_to=plan.retrieval.date_to,
        scope=retrieval_scope,
    )
    breakdown_started_at = perf_counter()
    breakdown = tool_registry.invoke(ToolId.FETCH_BREAKDOWN, breakdown_request)
    execution_trace = _append_tool_trace_step(
        execution_trace,
        step_id="tool.fetch_breakdown",
        input_ref="analysis_plan.retrieval",
        output_ref="breakdown_response",
        started_at=breakdown_started_at,
        warnings=_stringify_tool_warnings(breakdown.warnings),
    )
    ranked_items = breakdown.items
    warnings = [*state.warnings, *_stringify_tool_warnings(breakdown.warnings)]

    if plan.intent is AnalysisIntent.RANKING:
        attach_share_started_at = perf_counter()
        enriched = tool_registry.invoke(ToolId.ATTACH_BREAKDOWN_SHARE, breakdown)
        execution_trace = _append_tool_trace_step(
            execution_trace,
            step_id="tool.attach_breakdown_share",
            input_ref="breakdown_response",
            output_ref="breakdown_response_enriched",
            started_at=attach_share_started_at,
            warnings=_stringify_tool_warnings(enriched.warnings),
        )
        ranked_items = enriched.items
        warnings = [*warnings, *_stringify_tool_warnings(enriched.warnings)]

        if plan.ranking is not None:
            rank_request = RankItemsRequest(items=enriched.items, ranking=plan.ranking)
            ranking_started_at = perf_counter()
            if plan.ranking.mode.value == "top_k":
                ranked_items = tool_registry.invoke(ToolId.TOP_K, rank_request).items
                rank_step_id = "tool.top_k"
            else:
                ranked_items = tool_registry.invoke(ToolId.BOTTOM_K, rank_request).items
                rank_step_id = "tool.bottom_k"
            execution_trace = _append_tool_trace_step(
                execution_trace,
                step_id=rank_step_id,
                input_ref="ranking_request",
                output_ref="ranked_items",
                started_at=ranking_started_at,
            )

    summary_items = ", ".join(f"{item.label}={item.value:.2f}" for item in ranked_items)
    summary_prefix = "Ranking" if plan.intent is AnalysisIntent.RANKING else "Breakdown"
    summary = (
        f"{summary_prefix} for {plan.retrieval.metric.value} by {requested_dimension.value} "
        f"({plan.retrieval.date_from} to {plan.retrieval.date_to}): {summary_items}."
    )

    return {
        "analysis_artifacts": {
            **state.analysis_artifacts,
            "kind": "ranking" if plan.intent is AnalysisIntent.RANKING else "breakdown",
            "summary": summary,
        },
        "warnings": warnings,
        "execution_trace": execution_trace,
    }


def _run_trend_node(state: AgentState) -> dict[str, Any]:
    plan = state.analysis_plan
    if plan is None or plan.retrieval is None:
        return {
            "status": RunStatus.FAILED,
            "final_answer": "Trend failed: missing retrieval context.",
            "warnings": [*state.warnings, "trend_missing_context"],
        }

    tool_registry = get_tool_registry()
    execution_trace = state.execution_trace
    retrieval_scope = _build_retrieval_scope(state)
    timeseries_request = TimeseriesRequest(
        metric=plan.retrieval.metric,
        date_from=plan.retrieval.date_from,
        date_to=plan.retrieval.date_to,
        dimension=DimensionName.DAY,
        scope=retrieval_scope,
    )
    timeseries_started_at = perf_counter()
    timeseries = tool_registry.invoke(ToolId.FETCH_TIMESERIES, timeseries_request)
    execution_trace = _append_tool_trace_step(
        execution_trace,
        step_id="tool.fetch_timeseries",
        input_ref="analysis_plan.retrieval",
        output_ref="timeseries_response",
        started_at=timeseries_started_at,
        warnings=_stringify_tool_warnings(timeseries.warnings),
    )

    summary_parts = [
        (
            f"Trend for {plan.retrieval.metric.value} "
            f"({plan.retrieval.date_from} to {plan.retrieval.date_to})."
        )
    ]

    if plan.include_moving_average and len(timeseries.points) >= plan.moving_average_window:
        moving_average_request = MovingAverageRequest(
            points=timeseries.points,
            window_size=plan.moving_average_window,
        )
        moving_average_started_at = perf_counter()
        moving_average = tool_registry.invoke(ToolId.MOVING_AVERAGE, moving_average_request)
        execution_trace = _append_tool_trace_step(
            execution_trace,
            step_id="tool.moving_average",
            input_ref="moving_average_request",
            output_ref="moving_average_response",
            started_at=moving_average_started_at,
            warnings=_stringify_tool_warnings(moving_average.warnings),
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
            trend_slope_request = TrendSlopeRequest(points=timeseries.points)
            trend_slope_started_at = perf_counter()
            slope = tool_registry.invoke(ToolId.TREND_SLOPE, trend_slope_request)
            execution_trace = _append_tool_trace_step(
                execution_trace,
                step_id="tool.trend_slope",
                input_ref="trend_slope_request",
                output_ref="trend_slope_response",
                started_at=trend_slope_started_at,
                warnings=_stringify_tool_warnings(slope.warnings),
            )
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
        "warnings": [*state.warnings, *_stringify_tool_warnings(timeseries.warnings)],
        "execution_trace": execution_trace,
    }


def _run_business_query_node(state: AgentState) -> dict[str, Any]:
    plan = state.analysis_plan
    if plan is None or plan.business_query is None:
        return {
            "status": RunStatus.FAILED,
            "final_answer": "Business query failed: missing business query context.",
            "warnings": [*state.warnings, "business_query_missing_context"],
        }

    tool_registry = get_tool_registry()
    execution_trace = state.execution_trace
    retrieval_scope = _build_retrieval_scope(state)
    business_query = plan.business_query
    language = _question_language(state.user_question)

    if business_query.kind is BusinessQueryKind.ITEM_PERFORMANCE:
        if business_query.item_metric is None:
            return {
                "status": RunStatus.FAILED,
                "final_answer": "Business query failed: item metric is missing.",
                "warnings": [*state.warnings, "business_query_item_metric_missing"],
            }
        item_request = ItemPerformanceRequest(
            metric=business_query.item_metric,
            date_from=business_query.date_from,
            date_to=business_query.date_to,
            limit=business_query.limit,
            ranking_mode=business_query.ranking_mode,
            item_query=business_query.item_query,
            scope=retrieval_scope,
        )
        started_at = perf_counter()
        response = tool_registry.invoke(ToolId.FETCH_ITEM_PERFORMANCE, item_request)
        execution_trace = _append_tool_trace_step(
            execution_trace,
            step_id="tool.fetch_item_performance",
            input_ref="analysis_plan.business_query",
            output_ref="item_performance_response",
            started_at=started_at,
        )
        summary = _build_item_performance_summary(
            business_query=business_query,
            response=response,
            language=language,
        )
        return {
            "analysis_artifacts": {
                **state.analysis_artifacts,
                "kind": "item_performance",
                "summary": summary,
            },
            "warnings": state.warnings,
            "execution_trace": execution_trace,
        }

    if business_query.kind is BusinessQueryKind.CUSTOMER_SUMMARY:
        customer_request = CustomerSummaryRequest(
            date_from=business_query.date_from,
            date_to=business_query.date_to,
            scope=retrieval_scope,
        )
        started_at = perf_counter()
        response = tool_registry.invoke(ToolId.FETCH_CUSTOMER_SUMMARY, customer_request)
        execution_trace = _append_tool_trace_step(
            execution_trace,
            step_id="tool.fetch_customer_summary",
            input_ref="analysis_plan.business_query",
            output_ref="customer_summary_response",
            started_at=started_at,
        )
        summary = (
            f"Customer summary for {business_query.date_from} to {business_query.date_to}: "
            f"unique_clients={response.unique_clients}, "
            f"identified_order_count={response.identified_order_count}, "
            f"total_order_count={response.total_order_count}, "
            f"average_orders_per_identified_client="
            f"{response.average_orders_per_identified_client:.2f}."
        )
        return {
            "analysis_artifacts": {
                **state.analysis_artifacts,
                "kind": "customer_summary",
                "summary": summary,
            },
            "warnings": state.warnings,
            "execution_trace": execution_trace,
        }

    receipt_request = ReceiptSummaryRequest(
        date_from=business_query.date_from,
        date_to=business_query.date_to,
        scope=retrieval_scope,
    )
    started_at = perf_counter()
    response = tool_registry.invoke(ToolId.FETCH_RECEIPT_SUMMARY, receipt_request)
    execution_trace = _append_tool_trace_step(
        execution_trace,
        step_id="tool.fetch_receipt_summary",
        input_ref="analysis_plan.business_query",
        output_ref="receipt_summary_response",
        started_at=started_at,
    )
    status_summary = ", ".join(
        f"{status}={count}" for status, count in sorted(response.status_counts.items())
    ) or "no receipt statuses found"
    summary = (
        f"Receipt summary for {business_query.date_from} to {business_query.date_to}: "
        f"receipt_count={response.receipt_count}, "
        f"linked_order_count={response.linked_order_count}, "
        f"statuses: {status_summary}."
    )
    return {
        "analysis_artifacts": {
            **state.analysis_artifacts,
            "kind": "receipt_summary",
            "summary": summary,
        },
        "warnings": state.warnings,
        "execution_trace": execution_trace,
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
        "Չաջակցվող հարցում։"
        if language == "hy"
        else (
            "Неподдерживаемый запрос."
            if language == "ru"
            else "Unsupported request."
        )
    )
    supported_reports = (
        "Աջակցվող անալիտիկան ներառում է sales_total, gross_sales_total, "
        "order_count, average_check, quantity_sold, items_per_order, "
        "discounted_order_count, discounted_order_share և sales_by_source։"
        if language == "hy"
        else (
            "Поддерживаемая аналитика: sales_total, gross_sales_total, "
            "order_count, average_check, quantity_sold, items_per_order, "
            "discounted_order_count, discounted_order_share, sales_by_source."
            if language == "ru"
            else (
                "Supported analytics include sales_total, gross_sales_total, "
                "order_count, average_check, quantity_sold, items_per_order, "
                "discounted_order_count, discounted_order_share, sales_by_source."
            )
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
    graph.add_node("run_multi_report", _run_multi_report_node)
    graph.add_node("run_business_query", _run_business_query_node)
    graph.add_node("calc_metrics", _calc_metrics_node)
    graph.add_node("run_total", _run_total_node)
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
            PolicyRoute.RUN_MULTI_REPORT.value: "run_multi_report",
            PolicyRoute.RUN_BUSINESS_QUERY.value: "run_business_query",
            PolicyRoute.RUN_TOTAL.value: "run_total",
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
    graph.add_edge("run_multi_report", "compose_answer")
    graph.add_edge("run_business_query", "compose_answer")
    graph.add_edge("calc_metrics", "compose_answer")
    graph.add_edge("run_total", "compose_answer")
    graph.add_edge("run_comparison", "compose_answer")
    graph.add_edge("run_ranking", "compose_answer")
    graph.add_edge("run_trend", "compose_answer")
    graph.add_edge("compose_answer", END)
    graph.add_edge("smalltalk", END)
    graph.add_edge("clarify", END)
    graph.add_edge("reject", END)
    graph.add_edge("safe_answer", END)

    return graph.compile()
