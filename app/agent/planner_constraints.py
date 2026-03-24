from __future__ import annotations

from dataclasses import dataclass

from app.agent.metric_registry import (
    get_dimension_registry,
    get_metric_registry,
    is_dimension_allowed_for_metric,
)
from app.agent.operation_registry import (
    SemanticOperation,
    runtime_operations_for_intent,
    semantic_operations_for_intent,
)
from app.schemas.analysis import AnalysisIntent, DimensionName, MetricName, RankingMode
from app.schemas.tools import ToolOperation


@dataclass(frozen=True)
class PlannerConstraintDecision:
    allowed: bool
    reason_code: str
    reason_message: str
    required_metric_ids: tuple[str, ...] = ()
    required_dimension_ids: tuple[str, ...] = ()
    required_semantic_operations: tuple[SemanticOperation, ...] = ()
    required_runtime_operations: tuple[ToolOperation, ...] = ()


def evaluate_planner_constraints(
    *,
    plan_intent: AnalysisIntent,
    retrieval_metric: MetricName | None,
    previous_period_metric: MetricName | None,
    retrieval_dimension: DimensionName | None,
    ranking_mode: RankingMode | None,
    include_moving_average: bool,
    include_trend_slope: bool,
    has_scalar_calculations: bool,
) -> PlannerConstraintDecision:
    semantic_operations = semantic_operations_for_intent(plan_intent)
    runtime_operations = runtime_operations_for_intent(
        intent=plan_intent,
        ranking_mode=ranking_mode,
        include_moving_average=include_moving_average,
        include_trend_slope=include_trend_slope,
        has_scalar_calculations=has_scalar_calculations,
    )

    metric_registry = get_metric_registry()
    required_metric_ids: list[str] = []
    for metric in (retrieval_metric, previous_period_metric):
        if metric is None:
            continue
        metric_id = metric.value
        if metric_id not in metric_registry:
            return PlannerConstraintDecision(
                allowed=False,
                reason_code="unknown_metric_id",
                reason_message=f"Metric `{metric_id}` is not in canonical metric registry.",
            )
        if metric_id not in required_metric_ids:
            required_metric_ids.append(metric_id)

    required_dimension_ids: list[str] = []
    if retrieval_dimension is not None:
        dimension_id = retrieval_dimension.value
        if dimension_id not in get_dimension_registry():
            return PlannerConstraintDecision(
                allowed=False,
                reason_code="unknown_dimension_id",
                reason_message=(
                    f"Dimension `{dimension_id}` is not in canonical dimension registry."
                ),
            )
        required_dimension_ids.append(dimension_id)

        if retrieval_metric is not None and not is_dimension_allowed_for_metric(
            metric_id=retrieval_metric.value,
            dimension_id=dimension_id,
        ):
            return PlannerConstraintDecision(
                allowed=False,
                reason_code="dimension_not_supported_for_metric",
                reason_message=(
                    f"Dimension `{dimension_id}` is not allowed for metric "
                    f"`{retrieval_metric.value}`."
                ),
            )

    return PlannerConstraintDecision(
        allowed=True,
        reason_code="ok",
        reason_message="Plan satisfies canonical registry and operation constraints.",
        required_metric_ids=tuple(required_metric_ids),
        required_dimension_ids=tuple(required_dimension_ids),
        required_semantic_operations=semantic_operations,
        required_runtime_operations=runtime_operations,
    )
