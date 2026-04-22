from __future__ import annotations

from app.agent import planner_constraints as constraints_module
from app.agent.operation_registry import SemanticOperation
from app.agent.planner_constraints import evaluate_planner_constraints
from app.schemas.analysis import AnalysisIntent, DimensionName, MetricName, RankingMode
from app.schemas.tools import ToolOperation


def test_planner_constraints_emit_semantic_and_runtime_ops_for_comparison() -> None:
    decision = evaluate_planner_constraints(
        plan_intent=AnalysisIntent.COMPARISON,
        retrieval_metric=MetricName.SALES_TOTAL,
        previous_period_metric=MetricName.SALES_TOTAL,
        retrieval_dimension=None,
        ranking_mode=None,
        include_moving_average=False,
        include_trend_slope=False,
        has_scalar_calculations=True,
    )

    assert decision.allowed is True
    assert decision.required_semantic_operations == (
        SemanticOperation.TOTAL,
        SemanticOperation.COMPARE,
    )
    assert decision.required_runtime_operations == (
        ToolOperation.FETCH_TOTAL_METRIC,
        ToolOperation.COMPUTE_SCALAR_METRICS,
    )


def test_planner_constraints_emit_runtime_ops_for_ranking_top_k() -> None:
    decision = evaluate_planner_constraints(
        plan_intent=AnalysisIntent.RANKING,
        retrieval_metric=MetricName.SALES_TOTAL,
        previous_period_metric=None,
        retrieval_dimension=DimensionName.SOURCE,
        ranking_mode=RankingMode.TOP_K,
        include_moving_average=False,
        include_trend_slope=False,
        has_scalar_calculations=False,
    )

    assert decision.allowed is True
    assert decision.required_runtime_operations == (
        ToolOperation.FETCH_BREAKDOWN,
        ToolOperation.ATTACH_BREAKDOWN_SHARE,
        ToolOperation.TOP_K,
    )


def test_planner_constraints_reject_unknown_metric_id(monkeypatch) -> None:
    monkeypatch.setattr(constraints_module, "get_metric_registry", lambda: {})
    decision = evaluate_planner_constraints(
        plan_intent=AnalysisIntent.METRIC_TOTAL,
        retrieval_metric=MetricName.SALES_TOTAL,
        previous_period_metric=None,
        retrieval_dimension=None,
        ranking_mode=None,
        include_moving_average=False,
        include_trend_slope=False,
        has_scalar_calculations=False,
    )

    assert decision.allowed is False
    assert decision.reason_code == "unknown_metric_id"

