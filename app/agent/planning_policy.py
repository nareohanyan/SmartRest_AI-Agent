from __future__ import annotations

from datetime import date

from app.agent.live_capabilities import evaluate_live_retrieval_capability
from app.agent.planner_constraints import evaluate_planner_constraints
from app.core.config import Settings
from app.schemas.agent import PolicyRoute
from app.schemas.analysis import (
    AnalysisIntent,
    DimensionName,
    MetricName,
    RankingMode,
    RetrievalMode,
)
from app.schemas.base import SchemaModel
from app.schemas.reports import ReportFilters, ReportType
from app.schemas.tools import AccessStatus, ExportMode, ResolveScopeResponse, ToolOperation


class PolicyDecision(SchemaModel):
    route: PolicyRoute
    reason_code: str
    reason_message: str
    mapped_report_id: ReportType | None = None
    normalized_filters: ReportFilters | None = None
    allowed: bool


def evaluate_business_query_policy(
    *,
    date_from: date,
    date_to: date,
    scope: ResolveScopeResponse | None,
    settings: Settings,
    required_tool: ToolOperation,
    requested_branch_ids: list[str] | None = None,
    requested_export_mode: ExportMode | None = None,
) -> PolicyDecision:
    if scope is None or scope.status is AccessStatus.DENIED:
        return PolicyDecision(
            route=PolicyRoute.REJECT,
            reason_code="scope_denied",
            reason_message="Scope is missing or denied.",
            allowed=False,
        )

    day_span = (date_to - date_from).days + 1
    if day_span <= 0:
        return PolicyDecision(
            route=PolicyRoute.CLARIFY,
            reason_code="invalid_date_range",
            reason_message="Date range is invalid.",
            allowed=False,
        )
    if day_span > settings.planner_max_date_range_days:
        return PolicyDecision(
            route=PolicyRoute.CLARIFY,
            reason_code="date_range_too_wide",
            reason_message="Date range exceeds configured planning window.",
            allowed=False,
        )

    if requested_branch_ids:
        missing_branch_ids = _missing_branch_permissions(
            requested_branch_ids=requested_branch_ids,
            scope=scope,
        )
        if missing_branch_ids:
            return _reject_missing_branch(missing_branch_ids[0])

    if requested_export_mode is not None and not _is_export_mode_allowed(
        requested_export_mode=requested_export_mode,
        scope=scope,
    ):
        return _reject_export_mode(requested_export_mode)

    missing_tools = _missing_tool_permissions(required_tools=[required_tool], scope=scope)
    if missing_tools:
        return _reject_missing_tool(missing_tools[0])

    return PolicyDecision(
        route=PolicyRoute.RUN_BUSINESS_QUERY,
        reason_code="ok",
        reason_message="Plan is allowed for SmartRest business tool execution.",
        allowed=True,
    )


def _map_retrieval_to_report(
    *,
    mode: RetrievalMode,
    metric: MetricName,
    dimension: DimensionName | None,
) -> ReportType | None:
    if mode is RetrievalMode.TOTAL:
        if metric is MetricName.SALES_TOTAL:
            return ReportType.SALES_TOTAL
        if metric is MetricName.ORDER_COUNT:
            return ReportType.ORDER_COUNT
        if metric is MetricName.AVERAGE_CHECK:
            return ReportType.AVERAGE_CHECK
        return None

    if (
        mode is RetrievalMode.BREAKDOWN
        and metric is MetricName.SALES_TOTAL
        and dimension is DimensionName.SOURCE
    ):
        return ReportType.SALES_BY_SOURCE
    return None


def _estimated_tool_calls(intent: AnalysisIntent) -> int:
    if intent in {AnalysisIntent.METRIC_TOTAL, AnalysisIntent.BREAKDOWN}:
        return 2
    if intent is AnalysisIntent.COMPARISON:
        return 3
    if intent is AnalysisIntent.RANKING:
        return 3
    if intent is AnalysisIntent.TREND:
        return 4
    return 1


def _missing_metric_permissions(
    *,
    required_metric_ids: list[str],
    scope: ResolveScopeResponse,
) -> list[str]:
    allowed_metric_ids = _scope_metric_ids(scope)
    return [metric_id for metric_id in required_metric_ids if metric_id not in allowed_metric_ids]


def _missing_dimension_permissions(
    *,
    required_dimension_ids: list[str],
    scope: ResolveScopeResponse,
) -> list[str]:
    allowed_dimension_ids = _scope_dimension_ids(scope)
    return [
        dimension_id
        for dimension_id in required_dimension_ids
        if dimension_id not in allowed_dimension_ids
    ]


def _scope_metric_ids(scope: ResolveScopeResponse) -> set[str]:
    if scope.allowed_metric_ids is not None:
        return set(scope.allowed_metric_ids)
    return {metric.value for metric in (scope.allowed_metrics or [])}


def _scope_dimension_ids(scope: ResolveScopeResponse) -> set[str]:
    if scope.allowed_dimension_ids is not None:
        return set(scope.allowed_dimension_ids)
    return {dimension.value for dimension in (scope.allowed_dimensions or [])}


def _missing_tool_permissions(
    *,
    required_tools: list[ToolOperation],
    scope: ResolveScopeResponse,
) -> list[ToolOperation]:
    allowed_tools = scope.allowed_tool_operations or []
    return [tool for tool in required_tools if tool not in allowed_tools]


def _missing_branch_permissions(
    *,
    requested_branch_ids: list[str],
    scope: ResolveScopeResponse,
) -> list[str]:
    allowed_branch_ids = set(scope.allowed_branch_ids or [])
    if "*" in allowed_branch_ids:
        return []
    return [branch_id for branch_id in requested_branch_ids if branch_id not in allowed_branch_ids]


def _is_export_mode_allowed(
    *,
    requested_export_mode: ExportMode,
    scope: ResolveScopeResponse,
) -> bool:
    return requested_export_mode in (scope.allowed_export_modes or [])


def _reject_missing_metric(metric_id: str) -> PolicyDecision:
    return PolicyDecision(
        route=PolicyRoute.REJECT,
        reason_code="metric_not_allowed",
        reason_message=f"Metric `{metric_id}` is not allowed for this scope.",
        allowed=False,
    )


def _reject_missing_dimension(dimension_id: str) -> PolicyDecision:
    return PolicyDecision(
        route=PolicyRoute.REJECT,
        reason_code="dimension_not_allowed",
        reason_message=f"Dimension `{dimension_id}` is not allowed for this scope.",
        allowed=False,
    )


def _reject_missing_tool(tool: ToolOperation) -> PolicyDecision:
    return PolicyDecision(
        route=PolicyRoute.REJECT,
        reason_code="tool_not_allowed",
        reason_message=f"Tool operation `{tool.value}` is not allowed for this scope.",
        allowed=False,
    )


def _reject_missing_branch(branch_id: str) -> PolicyDecision:
    return PolicyDecision(
        route=PolicyRoute.REJECT,
        reason_code="branch_not_allowed",
        reason_message=f"Branch `{branch_id}` is not allowed for this scope.",
        allowed=False,
    )


def _reject_export_mode(export_mode: ExportMode) -> PolicyDecision:
    return PolicyDecision(
        route=PolicyRoute.REJECT,
        reason_code="export_mode_not_allowed",
        reason_message=f"Export mode `{export_mode.value}` is not allowed for this scope.",
        allowed=False,
    )


def evaluate_plan_policy(
    *,
    plan_intent: AnalysisIntent,
    retrieval_mode: RetrievalMode | None,
    retrieval_metric: MetricName | None,
    retrieval_dimension: DimensionName | None,
    date_from: date | None,
    date_to: date | None,
    scope: ResolveScopeResponse | None,
    settings: Settings,
    compare_to_previous_period: bool = False,
    previous_period_metric: MetricName | None = None,
    ranking_mode: RankingMode | None = None,
    include_moving_average: bool = False,
    include_trend_slope: bool = False,
    has_scalar_calculations: bool = False,
    requested_branch_ids: list[str] | None = None,
    requested_export_mode: ExportMode | None = None,
) -> PolicyDecision:
    if scope is None or scope.status is AccessStatus.DENIED:
        return PolicyDecision(
            route=PolicyRoute.REJECT,
            reason_code="scope_denied",
            reason_message="Scope is missing or denied.",
            allowed=False,
        )

    if plan_intent is AnalysisIntent.CLARIFY:
        return PolicyDecision(
            route=PolicyRoute.CLARIFY,
            reason_code="clarification_required",
            reason_message="Plan requires clarification before execution.",
            allowed=False,
        )

    if plan_intent is AnalysisIntent.SMALLTALK:
        return PolicyDecision(
            route=PolicyRoute.SMALLTALK,
            reason_code="smalltalk",
            reason_message="Greeting/smalltalk request handled by conversational route.",
            allowed=False,
        )

    if plan_intent is AnalysisIntent.UNSUPPORTED:
        if settings.planner_allow_safe_general_topics:
            return PolicyDecision(
                route=PolicyRoute.SAFE_ANSWER,
                reason_code="unsupported_safe_answer",
                reason_message="Unsupported business request handled by safe answer path.",
                allowed=False,
            )
        return PolicyDecision(
            route=PolicyRoute.REJECT,
            reason_code="unsupported_request",
            reason_message="Unsupported business request rejected by policy.",
            allowed=False,
        )

    if retrieval_mode is None or retrieval_metric is None or date_from is None or date_to is None:
        return PolicyDecision(
            route=PolicyRoute.CLARIFY,
            reason_code="missing_retrieval",
            reason_message="Plan is missing required retrieval context.",
            allowed=False,
        )

    day_span = (date_to - date_from).days + 1
    if day_span <= 0:
        return PolicyDecision(
            route=PolicyRoute.CLARIFY,
            reason_code="invalid_date_range",
            reason_message="Date range is invalid.",
            allowed=False,
        )
    if day_span > settings.planner_max_date_range_days:
        return PolicyDecision(
            route=PolicyRoute.CLARIFY,
            reason_code="date_range_too_wide",
            reason_message="Date range exceeds configured planning window.",
            allowed=False,
        )

    if _estimated_tool_calls(plan_intent) > settings.planner_max_tool_calls:
        return PolicyDecision(
            route=PolicyRoute.CLARIFY,
            reason_code="tool_budget_exceeded",
            reason_message="Planned execution exceeds allowed tool budget.",
            allowed=False,
        )

    if requested_branch_ids:
        missing_branch_ids = _missing_branch_permissions(
            requested_branch_ids=requested_branch_ids,
            scope=scope,
        )
        if missing_branch_ids:
            return _reject_missing_branch(missing_branch_ids[0])

    if requested_export_mode is not None and not _is_export_mode_allowed(
        requested_export_mode=requested_export_mode,
        scope=scope,
    ):
        return _reject_export_mode(requested_export_mode)

    planner_constraints = evaluate_planner_constraints(
        plan_intent=plan_intent,
        retrieval_metric=retrieval_metric,
        previous_period_metric=previous_period_metric,
        retrieval_dimension=retrieval_dimension,
        ranking_mode=ranking_mode,
        include_moving_average=include_moving_average,
        include_trend_slope=include_trend_slope,
        has_scalar_calculations=has_scalar_calculations,
    )
    if not planner_constraints.allowed:
        return PolicyDecision(
            route=PolicyRoute.REJECT,
            reason_code=planner_constraints.reason_code,
            reason_message=planner_constraints.reason_message,
            allowed=False,
        )

    missing_metric_ids = _missing_metric_permissions(
        required_metric_ids=list(planner_constraints.required_metric_ids),
        scope=scope,
    )
    if missing_metric_ids:
        return _reject_missing_metric(missing_metric_ids[0])

    missing_dimension_ids = _missing_dimension_permissions(
        required_dimension_ids=list(planner_constraints.required_dimension_ids),
        scope=scope,
    )
    if missing_dimension_ids:
        return _reject_missing_dimension(missing_dimension_ids[0])

    live_capability = evaluate_live_retrieval_capability(
        retrieval_mode=retrieval_mode,
        retrieval_metric=retrieval_metric,
        retrieval_dimension=retrieval_dimension,
    )
    if not live_capability.allowed:
        return PolicyDecision(
            route=PolicyRoute.REJECT,
            reason_code=live_capability.reason_code,
            reason_message=live_capability.reason_message,
            allowed=False,
        )

    if plan_intent is AnalysisIntent.METRIC_TOTAL:
        mapped_report_id = _map_retrieval_to_report(
            mode=retrieval_mode,
            metric=retrieval_metric,
            dimension=retrieval_dimension,
        )
        if mapped_report_id is not None:
            if mapped_report_id not in scope.allowed_report_ids:
                return PolicyDecision(
                    route=PolicyRoute.REJECT,
                    reason_code="report_not_allowed",
                    reason_message="Mapped report is not allowed for this scope.",
                    allowed=False,
                )
            return PolicyDecision(
                route=PolicyRoute.PREPARE_LEGACY_REPORT,
                reason_code="ok",
                reason_message="Plan is allowed and mapped to legacy report execution.",
                mapped_report_id=mapped_report_id,
                normalized_filters=ReportFilters(date_from=date_from, date_to=date_to),
                allowed=True,
            )

        required_tools = list(planner_constraints.required_runtime_operations)
        missing_tools = _missing_tool_permissions(required_tools=required_tools, scope=scope)
        if missing_tools:
            return _reject_missing_tool(missing_tools[0])
        return PolicyDecision(
            route=PolicyRoute.RUN_TOTAL,
            reason_code="ok",
            reason_message="Plan is allowed for dynamic total metric execution.",
            allowed=True,
        )

    if plan_intent is AnalysisIntent.BREAKDOWN:
        if retrieval_mode is not RetrievalMode.BREAKDOWN or retrieval_dimension is None:
            return PolicyDecision(
                route=PolicyRoute.REJECT,
                reason_code="unsupported_retrieval_mode",
                reason_message="Breakdown requires breakdown retrieval with dimension.",
                allowed=False,
            )
        required_tools = list(planner_constraints.required_runtime_operations)
        missing_tools = _missing_tool_permissions(required_tools=required_tools, scope=scope)
        if missing_tools:
            return _reject_missing_tool(missing_tools[0])
        return PolicyDecision(
            route=PolicyRoute.RUN_RANKING,
            reason_code="ok",
            reason_message="Plan is allowed for breakdown execution.",
            allowed=True,
        )

    if plan_intent is AnalysisIntent.COMPARISON:
        if retrieval_mode is not RetrievalMode.TOTAL:
            return PolicyDecision(
                route=PolicyRoute.REJECT,
                reason_code="unsupported_retrieval_mode",
                reason_message="Comparison requires total retrieval mode.",
                allowed=False,
            )
        required_tools = list(planner_constraints.required_runtime_operations)
        missing_tools = _missing_tool_permissions(required_tools=required_tools, scope=scope)
        if missing_tools:
            return _reject_missing_tool(missing_tools[0])
        return PolicyDecision(
            route=PolicyRoute.RUN_COMPARISON,
            reason_code="ok",
            reason_message="Plan is allowed for comparison execution.",
            allowed=True,
        )

    if plan_intent is AnalysisIntent.RANKING:
        if retrieval_mode is not RetrievalMode.BREAKDOWN or retrieval_dimension is None:
            return PolicyDecision(
                route=PolicyRoute.REJECT,
                reason_code="unsupported_retrieval_mode",
                reason_message="Ranking requires breakdown retrieval with dimension.",
                allowed=False,
            )
        required_tools = list(planner_constraints.required_runtime_operations)
        missing_tools = _missing_tool_permissions(required_tools=required_tools, scope=scope)
        if missing_tools:
            return _reject_missing_tool(missing_tools[0])
        return PolicyDecision(
            route=PolicyRoute.RUN_RANKING,
            reason_code="ok",
            reason_message="Plan is allowed for ranking execution.",
            allowed=True,
        )

    if plan_intent is AnalysisIntent.TREND:
        if retrieval_mode is not RetrievalMode.TIMESERIES:
            return PolicyDecision(
                route=PolicyRoute.REJECT,
                reason_code="unsupported_retrieval_mode",
                reason_message="Trend requires timeseries retrieval mode.",
                allowed=False,
            )
        required_tools = list(planner_constraints.required_runtime_operations)
        missing_tools = _missing_tool_permissions(required_tools=required_tools, scope=scope)
        if missing_tools:
            return _reject_missing_tool(missing_tools[0])
        return PolicyDecision(
            route=PolicyRoute.RUN_TREND,
            reason_code="ok",
            reason_message="Plan is allowed for trend execution.",
            allowed=True,
        )

    return PolicyDecision(
        route=PolicyRoute.REJECT,
        reason_code="unhandled_intent",
        reason_message="Policy does not handle this intent.",
        allowed=False,
    )
