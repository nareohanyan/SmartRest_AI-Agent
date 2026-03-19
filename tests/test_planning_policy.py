from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.agent.planning_policy import evaluate_plan_policy
from app.schemas.agent import PolicyRoute
from app.schemas.analysis import AnalysisIntent, DimensionName, MetricName, RetrievalMode
from app.schemas.reports import ReportType
from app.schemas.tools import AccessStatus, ResolveScopeResponse


def _settings(**overrides: object) -> SimpleNamespace:
    payload = {
        "planner_max_date_range_days": 366,
        "planner_max_tool_calls": 6,
        "planner_allow_safe_general_topics": True,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _granted_scope(*allowed: ReportType) -> ResolveScopeResponse:
    return ResolveScopeResponse(
        status=AccessStatus.GRANTED,
        allowed_report_ids=list(allowed),
        denial_reason=None,
    )


def test_policy_denies_when_scope_is_denied() -> None:
    decision = evaluate_plan_policy(
        plan_intent=AnalysisIntent.METRIC_TOTAL,
        retrieval_mode=RetrievalMode.TOTAL,
        retrieval_metric=MetricName.SALES_TOTAL,
        retrieval_dimension=None,
        date_from=date(2026, 3, 1),
        date_to=date(2026, 3, 7),
        scope=ResolveScopeResponse(
            status=AccessStatus.DENIED,
            allowed_report_ids=[],
            denial_reason="no_access",
        ),
        settings=_settings(),
    )

    assert decision.route is PolicyRoute.REJECT
    assert decision.allowed is False
    assert decision.reason_code == "scope_denied"


def test_policy_maps_metric_total_to_legacy_report_route() -> None:
    decision = evaluate_plan_policy(
        plan_intent=AnalysisIntent.METRIC_TOTAL,
        retrieval_mode=RetrievalMode.TOTAL,
        retrieval_metric=MetricName.SALES_TOTAL,
        retrieval_dimension=None,
        date_from=date(2026, 3, 1),
        date_to=date(2026, 3, 7),
        scope=_granted_scope(ReportType.SALES_TOTAL),
        settings=_settings(),
    )

    assert decision.route is PolicyRoute.PREPARE_LEGACY_REPORT
    assert decision.allowed is True
    assert decision.mapped_report_id is ReportType.SALES_TOTAL
    assert decision.normalized_filters is not None


def test_policy_returns_safe_answer_for_unsupported_when_enabled() -> None:
    decision = evaluate_plan_policy(
        plan_intent=AnalysisIntent.UNSUPPORTED,
        retrieval_mode=None,
        retrieval_metric=None,
        retrieval_dimension=None,
        date_from=None,
        date_to=None,
        scope=_granted_scope(ReportType.SALES_TOTAL),
        settings=_settings(planner_allow_safe_general_topics=True),
    )

    assert decision.route is PolicyRoute.SAFE_ANSWER
    assert decision.reason_code == "unsupported_safe_answer"


def test_policy_routes_smalltalk_to_smalltalk_node() -> None:
    decision = evaluate_plan_policy(
        plan_intent=AnalysisIntent.SMALLTALK,
        retrieval_mode=None,
        retrieval_metric=None,
        retrieval_dimension=None,
        date_from=None,
        date_to=None,
        scope=_granted_scope(ReportType.SALES_TOTAL),
        settings=_settings(),
    )

    assert decision.route is PolicyRoute.SMALLTALK
    assert decision.reason_code == "smalltalk"
    assert decision.allowed is False


def test_policy_rejects_when_date_range_is_too_wide() -> None:
    decision = evaluate_plan_policy(
        plan_intent=AnalysisIntent.METRIC_TOTAL,
        retrieval_mode=RetrievalMode.TOTAL,
        retrieval_metric=MetricName.ORDER_COUNT,
        retrieval_dimension=None,
        date_from=date(2025, 1, 1),
        date_to=date(2026, 3, 7),
        scope=_granted_scope(ReportType.ORDER_COUNT),
        settings=_settings(planner_max_date_range_days=30),
    )

    assert decision.route is PolicyRoute.CLARIFY
    assert decision.reason_code == "date_range_too_wide"
    assert decision.allowed is False


def test_policy_rejects_ranking_without_source_breakdown() -> None:
    decision = evaluate_plan_policy(
        plan_intent=AnalysisIntent.RANKING,
        retrieval_mode=RetrievalMode.TOTAL,
        retrieval_metric=MetricName.SALES_TOTAL,
        retrieval_dimension=DimensionName.SOURCE,
        date_from=date(2026, 3, 1),
        date_to=date(2026, 3, 7),
        scope=_granted_scope(ReportType.SALES_TOTAL),
        settings=_settings(),
    )

    assert decision.route is PolicyRoute.REJECT
    assert decision.reason_code == "unsupported_retrieval_mode"
