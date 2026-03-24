from __future__ import annotations

from datetime import date

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
from app.schemas.tools import AccessStatus, ResolveScopeResponse, ToolOperation


class PolicyDecision(SchemaModel):
    route: PolicyRoute
    reason_code: str
    reason_message: str
    mapped_report_id: ReportType | None = None
    normalized_filters: ReportFilters | None = None
    allowed: bool


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
    required_metrics: list[MetricName],
    scope: ResolveScopeResponse,
) -> list[MetricName]:
    allowed_metrics = scope.allowed_metrics or []
    return [metric for metric in required_metrics if metric not in allowed_metrics]


def _missing_dimension_permissions(
    *,
    required_dimensions: list[DimensionName],
    scope: ResolveScopeResponse,
) -> list[DimensionName]:
    allowed_dimensions = scope.allowed_dimensions or []
    return [dimension for dimension in required_dimensions if dimension not in allowed_dimensions]


def _missing_tool_permissions(
    *,
    required_tools: list[ToolOperation],
    scope: ResolveScopeResponse,
) -> list[ToolOperation]:
    allowed_tools = scope.allowed_tool_operations or []
    return [tool for tool in required_tools if tool not in allowed_tools]


def _reject_missing_metric(metric: MetricName) -> PolicyDecision:
    return PolicyDecision(
        route=PolicyRoute.REJECT,
        reason_code="metric_not_allowed",
        reason_message=f"Metric `{metric.value}` is not allowed for this scope.",
        allowed=False,
    )


def _reject_missing_dimension(dimension: DimensionName) -> PolicyDecision:
    return PolicyDecision(
        route=PolicyRoute.REJECT,
        reason_code="dimension_not_allowed",
        reason_message=f"Dimension `{dimension.value}` is not allowed for this scope.",
        allowed=False,
    )


def _reject_missing_tool(tool: ToolOperation) -> PolicyDecision:
    return PolicyDecision(
        route=PolicyRoute.REJECT,
        reason_code="tool_not_allowed",
        reason_message=f"Tool operation `{tool.value}` is not allowed for this scope.",
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

    if plan_intent in {AnalysisIntent.METRIC_TOTAL, AnalysisIntent.BREAKDOWN}:
        mapped_report_id = _map_retrieval_to_report(
            mode=retrieval_mode,
            metric=retrieval_metric,
            dimension=retrieval_dimension,
        )
        if mapped_report_id is None:
            return PolicyDecision(
                route=PolicyRoute.REJECT,
                reason_code="unsupported_metric",
                reason_message="No supported report mapping for this metric/dimension.",
                allowed=False,
            )
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

    if plan_intent is AnalysisIntent.COMPARISON:
        if retrieval_mode is not RetrievalMode.TOTAL:
            return PolicyDecision(
                route=PolicyRoute.REJECT,
                reason_code="unsupported_retrieval_mode",
                reason_message="Comparison requires total retrieval mode.",
                allowed=False,
            )
        required_metrics = [retrieval_metric]
        if compare_to_previous_period and previous_period_metric is not None:
            required_metrics.append(previous_period_metric)
        missing_metrics = _missing_metric_permissions(
            required_metrics=[metric for metric in required_metrics if metric is not None],
            scope=scope,
        )
        if missing_metrics:
            return _reject_missing_metric(missing_metrics[0])

        required_tools = [ToolOperation.FETCH_TOTAL_METRIC]
        if has_scalar_calculations:
            required_tools.append(ToolOperation.COMPUTE_SCALAR_METRICS)
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
        if (
            retrieval_mode is not RetrievalMode.BREAKDOWN
            or retrieval_dimension is not DimensionName.SOURCE
        ):
            return PolicyDecision(
                route=PolicyRoute.REJECT,
                reason_code="unsupported_retrieval_mode",
                reason_message="Ranking requires source breakdown retrieval.",
                allowed=False,
            )
        missing_metrics = _missing_metric_permissions(
            required_metrics=[retrieval_metric] if retrieval_metric is not None else [],
            scope=scope,
        )
        if missing_metrics:
            return _reject_missing_metric(missing_metrics[0])

        missing_dimensions = _missing_dimension_permissions(
            required_dimensions=[DimensionName.SOURCE],
            scope=scope,
        )
        if missing_dimensions:
            return _reject_missing_dimension(missing_dimensions[0])

        required_tools = [ToolOperation.FETCH_BREAKDOWN, ToolOperation.ATTACH_BREAKDOWN_SHARE]
        if ranking_mode is RankingMode.TOP_K:
            required_tools.append(ToolOperation.TOP_K)
        if ranking_mode is RankingMode.BOTTOM_K:
            required_tools.append(ToolOperation.BOTTOM_K)
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
        missing_metrics = _missing_metric_permissions(
            required_metrics=[retrieval_metric] if retrieval_metric is not None else [],
            scope=scope,
        )
        if missing_metrics:
            return _reject_missing_metric(missing_metrics[0])

        missing_dimensions = _missing_dimension_permissions(
            required_dimensions=[DimensionName.DAY],
            scope=scope,
        )
        if missing_dimensions:
            return _reject_missing_dimension(missing_dimensions[0])

        required_tools = [ToolOperation.FETCH_TIMESERIES]
        if include_moving_average:
            required_tools.append(ToolOperation.MOVING_AVERAGE)
        if include_trend_slope:
            required_tools.append(ToolOperation.TREND_SLOPE)
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
