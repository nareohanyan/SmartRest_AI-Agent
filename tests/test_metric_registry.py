from __future__ import annotations

from app.agent.metric_registry import (
    MetricType,
    evaluate_metric_operational_trust,
    get_dimension_registry,
    get_metric_registry,
    resolve_dimension_id,
    resolve_metric_id,
)


def test_metric_registry_contains_canonical_core_metrics() -> None:
    registry = get_metric_registry()

    assert "sales_total" in registry
    assert "order_count" in registry
    assert "average_check" in registry
    assert registry["average_check"].metric_type is MetricType.DERIVED


def test_average_check_formula_ast_and_dependencies_are_consistent() -> None:
    average_check = get_metric_registry()["average_check"]
    assert average_check.formula_ast is not None
    assert average_check.dependencies == ("sales_total", "completed_order_count")
    assert average_check.operational_trust is not None
    assert average_check.operational_trust.source_entity == "derived:average_check"


def test_dimension_registry_alias_resolution() -> None:
    dimensions = get_dimension_registry()
    assert "source" in dimensions
    assert resolve_dimension_id("delivery source") == "source"
    assert resolve_metric_id("revenue") == "sales_total"


def test_operational_trust_warnings_for_stale_and_quality_failures() -> None:
    warnings = evaluate_metric_operational_trust(
        metric_id="sales_total",
        observed_freshness_lag_minutes=120,
        failed_quality_checks={"sales_non_negative"},
    )

    assert "trust:freshness_stale" in warnings
    assert "trust:quality_failed:sales_non_negative" in warnings
