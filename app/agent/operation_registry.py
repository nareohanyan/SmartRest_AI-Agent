from __future__ import annotations

from enum import Enum

from app.schemas.analysis import AnalysisIntent, RankingMode
from app.schemas.tools import ToolOperation


class SemanticOperation(str, Enum):
    TOTAL = "total"
    BREAKDOWN = "breakdown"
    TIMESERIES = "timeseries"
    COMPARE = "compare"
    RANK = "rank"
    SHARE = "share"
    TREND = "trend"


_SEMANTIC_TO_RUNTIME_MAP: dict[SemanticOperation, tuple[ToolOperation, ...]] = {
    SemanticOperation.TOTAL: (ToolOperation.FETCH_TOTAL_METRIC,),
    SemanticOperation.BREAKDOWN: (ToolOperation.FETCH_BREAKDOWN,),
    SemanticOperation.TIMESERIES: (ToolOperation.FETCH_TIMESERIES,),
    SemanticOperation.COMPARE: (ToolOperation.FETCH_TOTAL_METRIC,),
    SemanticOperation.RANK: (ToolOperation.FETCH_BREAKDOWN,),
    SemanticOperation.SHARE: (ToolOperation.ATTACH_BREAKDOWN_SHARE,),
    SemanticOperation.TREND: (ToolOperation.FETCH_TIMESERIES,),
}


def semantic_operations_for_intent(intent: AnalysisIntent) -> tuple[SemanticOperation, ...]:
    if intent is AnalysisIntent.METRIC_TOTAL:
        return (SemanticOperation.TOTAL,)
    if intent is AnalysisIntent.BREAKDOWN:
        return (SemanticOperation.BREAKDOWN,)
    if intent is AnalysisIntent.COMPARISON:
        return (SemanticOperation.TOTAL, SemanticOperation.COMPARE)
    if intent is AnalysisIntent.RANKING:
        return (
            SemanticOperation.BREAKDOWN,
            SemanticOperation.SHARE,
            SemanticOperation.RANK,
        )
    if intent is AnalysisIntent.TREND:
        return (SemanticOperation.TIMESERIES, SemanticOperation.TREND)
    return ()


def runtime_operations_for_semantic(
    semantic_operations: tuple[SemanticOperation, ...],
) -> tuple[ToolOperation, ...]:
    ordered: list[ToolOperation] = []
    seen: set[ToolOperation] = set()
    for semantic_operation in semantic_operations:
        for runtime_operation in _SEMANTIC_TO_RUNTIME_MAP[semantic_operation]:
            if runtime_operation in seen:
                continue
            seen.add(runtime_operation)
            ordered.append(runtime_operation)
    return tuple(ordered)


def runtime_operations_for_intent(
    *,
    intent: AnalysisIntent,
    ranking_mode: RankingMode | None,
    include_moving_average: bool,
    include_trend_slope: bool,
    has_scalar_calculations: bool,
) -> tuple[ToolOperation, ...]:
    semantic_operations = semantic_operations_for_intent(intent)
    base_operations = list(runtime_operations_for_semantic(semantic_operations))

    if intent is AnalysisIntent.COMPARISON and has_scalar_calculations:
        base_operations.append(ToolOperation.COMPUTE_SCALAR_METRICS)

    if intent is AnalysisIntent.RANKING:
        if ranking_mode is RankingMode.TOP_K:
            base_operations.append(ToolOperation.TOP_K)
        if ranking_mode is RankingMode.BOTTOM_K:
            base_operations.append(ToolOperation.BOTTOM_K)

    if intent is AnalysisIntent.TREND:
        if include_moving_average:
            base_operations.append(ToolOperation.MOVING_AVERAGE)
        if include_trend_slope:
            base_operations.append(ToolOperation.TREND_SLOPE)

    ordered: list[ToolOperation] = []
    seen: set[ToolOperation] = set()
    for operation in base_operations:
        if operation in seen:
            continue
        seen.add(operation)
        ordered.append(operation)

    return tuple(ordered)

