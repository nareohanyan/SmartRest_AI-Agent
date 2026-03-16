"""Deterministic behavior tests for compute_metrics_tool (C2)."""

from __future__ import annotations

from decimal import Decimal

from app.agent.calc_tools import compute_metrics_tool
from app.schemas.calculations import (
    CalculationWarningCode,
    ComputeMetricsRequest,
)


def _base_metrics() -> dict[str, Decimal]:
    return {
        "sales_current": Decimal("12345.67"),
        "sales_previous": Decimal("10000.00"),
        "orders": Decimal("345"),
        "days": Decimal("7"),
        "source_a": Decimal("4100.00"),
        "source_b": Decimal("2200.00"),
        "weight_a": Decimal("3"),
        "weight_b": Decimal("7"),
    }


def test_compute_metrics_tool_happy_path_all_v1_formulas() -> None:
    request = ComputeMetricsRequest.model_validate(
        {
            "base_metrics": _base_metrics(),
            "calculations": [
                {
                    "formula": "delta",
                    "current_key": "sales_current",
                    "previous_key": "sales_previous",
                    "output_key": "sales_delta",
                },
                {
                    "formula": "percent_change",
                    "current_key": "sales_current",
                    "previous_key": "sales_previous",
                    "output_key": "sales_percent_change",
                },
                {
                    "formula": "ratio",
                    "numerator_key": "sales_current",
                    "denominator_key": "orders",
                    "output_key": "sales_per_order",
                },
                {
                    "formula": "share_percent",
                    "part_key": "source_a",
                    "total_key": "sales_current",
                    "output_key": "source_a_share",
                },
                {
                    "formula": "average",
                    "value_keys": ["source_a", "source_b"],
                    "output_key": "sources_avg",
                },
                {
                    "formula": "weighted_average",
                    "value_keys": ["source_a", "source_b"],
                    "weight_keys": ["weight_a", "weight_b"],
                    "output_key": "sources_weighted_avg",
                },
                {
                    "formula": "per_day_rate",
                    "metric_key": "sales_current",
                    "day_count_key": "days",
                    "output_key": "sales_per_day",
                },
            ],
            "precision": 2,
            "rounding_mode": "half_up",
        }
    )

    response = compute_metrics_tool(request)

    derived = {metric.key: metric for metric in response.derived_metrics}
    assert response.warnings == []
    assert list(derived) == [
        "sales_delta",
        "sales_percent_change",
        "sales_per_order",
        "source_a_share",
        "sources_avg",
        "sources_weighted_avg",
        "sales_per_day",
    ]
    assert derived["sales_delta"].value == Decimal("2345.67")
    assert derived["sales_percent_change"].value == Decimal("23.46")
    assert derived["sales_per_order"].value == Decimal("35.78")
    assert derived["source_a_share"].value == Decimal("33.21")
    assert derived["sources_avg"].value == Decimal("3150.00")
    assert derived["sources_weighted_avg"].value == Decimal("2770.00")
    assert derived["sales_per_day"].value == Decimal("1763.67")


def test_compute_metrics_tool_division_by_zero_returns_none_and_warning() -> None:
    request = ComputeMetricsRequest.model_validate(
        {
            "base_metrics": {
                "current": Decimal("100"),
                "previous": Decimal("0"),
                "numerator": Decimal("10"),
                "denominator": Decimal("0"),
                "part": Decimal("2"),
                "total": Decimal("0"),
                "metric": Decimal("50"),
                "days": Decimal("0"),
            },
            "calculations": [
                {
                    "formula": "percent_change",
                    "current_key": "current",
                    "previous_key": "previous",
                    "output_key": "pc",
                },
                {
                    "formula": "ratio",
                    "numerator_key": "numerator",
                    "denominator_key": "denominator",
                    "output_key": "ratio",
                },
                {
                    "formula": "share_percent",
                    "part_key": "part",
                    "total_key": "total",
                    "output_key": "share",
                },
                {
                    "formula": "per_day_rate",
                    "metric_key": "metric",
                    "day_count_key": "days",
                    "output_key": "daily",
                },
            ],
        }
    )

    response = compute_metrics_tool(request)

    assert response.warnings == [CalculationWarningCode.DIVISION_BY_ZERO]
    assert all(metric.value is None for metric in response.derived_metrics)
    assert all(
        metric.warnings == [CalculationWarningCode.DIVISION_BY_ZERO]
        for metric in response.derived_metrics
    )


def test_compute_metrics_tool_missing_operands_return_none() -> None:
    request = ComputeMetricsRequest.model_validate(
        {
            "base_metrics": {"current": Decimal("120")},
            "calculations": [
                {
                    "formula": "delta",
                    "current_key": "current",
                    "previous_key": "missing_previous",
                    "output_key": "delta",
                },
                {
                    "formula": "average",
                    "value_keys": ["current", "missing_value"],
                    "output_key": "avg",
                },
            ],
        }
    )

    response = compute_metrics_tool(request)

    assert response.warnings == [CalculationWarningCode.MISSING_OPERAND]
    assert [metric.value for metric in response.derived_metrics] == [None, None]
    assert all(
        CalculationWarningCode.MISSING_OPERAND in metric.warnings
        for metric in response.derived_metrics
    )


def test_compute_metrics_tool_weighted_average_invalid_weight_sum() -> None:
    request = ComputeMetricsRequest.model_validate(
        {
            "base_metrics": {
                "value_a": Decimal("4"),
                "value_b": Decimal("6"),
                "weight_a": Decimal("0"),
                "weight_b": Decimal("0"),
            },
            "calculations": [
                {
                    "formula": "weighted_average",
                    "value_keys": ["value_a", "value_b"],
                    "weight_keys": ["weight_a", "weight_b"],
                    "output_key": "weighted",
                }
            ],
        }
    )

    response = compute_metrics_tool(request)

    assert response.derived_metrics[0].value is None
    assert response.derived_metrics[0].warnings == [CalculationWarningCode.INVALID_WEIGHT_SUM]
    assert response.warnings == [CalculationWarningCode.INVALID_WEIGHT_SUM]


def test_compute_metrics_tool_non_numeric_input_warning() -> None:
    request = ComputeMetricsRequest.model_validate(
        {
            "base_metrics": {
                "numerator": Decimal("10"),
                "denominator": Decimal("2"),
            },
            "calculations": [
                {
                    "formula": "ratio",
                    "numerator_key": "numerator",
                    "denominator_key": "denominator",
                    "output_key": "ratio",
                }
            ],
        }
    )
    request.base_metrics["denominator"] = "not-a-number"  # type: ignore[assignment]

    response = compute_metrics_tool(request)

    assert response.derived_metrics[0].value is None
    assert response.derived_metrics[0].warnings == [CalculationWarningCode.NON_NUMERIC_INPUT]
    assert response.warnings == [CalculationWarningCode.NON_NUMERIC_INPUT]


def test_compute_metrics_tool_rounding_mode_half_up_vs_half_even() -> None:
    half_up = ComputeMetricsRequest.model_validate(
        {
            "base_metrics": {
                "numerator": Decimal("1"),
                "denominator": Decimal("8"),
            },
            "calculations": [
                {
                    "formula": "ratio",
                    "numerator_key": "numerator",
                    "denominator_key": "denominator",
                    "output_key": "ratio",
                }
            ],
            "precision": 2,
            "rounding_mode": "half_up",
        }
    )
    half_even = ComputeMetricsRequest.model_validate(
        {
            "base_metrics": {
                "numerator": Decimal("1"),
                "denominator": Decimal("8"),
            },
            "calculations": [
                {
                    "formula": "ratio",
                    "numerator_key": "numerator",
                    "denominator_key": "denominator",
                    "output_key": "ratio",
                }
            ],
            "precision": 2,
            "rounding_mode": "half_even",
        }
    )

    half_up_response = compute_metrics_tool(half_up)
    half_even_response = compute_metrics_tool(half_even)

    assert half_up_response.derived_metrics[0].value == Decimal("0.13")
    assert half_even_response.derived_metrics[0].value == Decimal("0.12")
