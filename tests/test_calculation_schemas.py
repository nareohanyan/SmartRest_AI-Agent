"""Contract tests for calculation schema boundaries (C1)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.calculations import (
    CalculationFormula,
    CalculationWarningCode,
    ComputeMetricsRequest,
    ComputeMetricsResponse,
)


def _base_metrics() -> dict[str, Decimal]:
    return {
        "sales_total_current": Decimal("12345.67"),
        "sales_total_previous": Decimal("10000.00"),
        "order_count": Decimal("345"),
        "days_in_range": Decimal("7"),
        "source_a": Decimal("4100.00"),
        "source_b": Decimal("2200.00"),
        "weight_a": Decimal("3"),
        "weight_b": Decimal("7"),
    }


def test_compute_metrics_request_accepts_all_v1_formula_specs() -> None:
    request = ComputeMetricsRequest.model_validate(
        {
            "base_metrics": _base_metrics(),
            "calculations": [
                {
                    "formula": "delta",
                    "current_key": "sales_total_current",
                    "previous_key": "sales_total_previous",
                    "output_key": "sales_delta",
                },
                {
                    "formula": "percent_change",
                    "current_key": "sales_total_current",
                    "previous_key": "sales_total_previous",
                    "output_key": "sales_percent_change",
                },
                {
                    "formula": "ratio",
                    "numerator_key": "sales_total_current",
                    "denominator_key": "order_count",
                    "output_key": "sales_per_order",
                },
                {
                    "formula": "share_percent",
                    "part_key": "source_a",
                    "total_key": "sales_total_current",
                    "output_key": "source_a_share_percent",
                },
                {
                    "formula": "average",
                    "value_keys": ["source_a", "source_b"],
                    "output_key": "avg_sources",
                },
                {
                    "formula": "weighted_average",
                    "value_keys": ["source_a", "source_b"],
                    "weight_keys": ["weight_a", "weight_b"],
                    "output_key": "weighted_avg_sources",
                },
                {
                    "formula": "per_day_rate",
                    "metric_key": "sales_total_current",
                    "day_count_key": "days_in_range",
                    "output_key": "sales_per_day",
                },
            ],
            "precision": 2,
            "rounding_mode": "half_up",
        }
    )

    assert len(request.calculations) == 7
    assert request.precision == 2
    assert request.rounding_mode.value == "half_up"


def test_compute_metrics_request_rejects_invalid_formula() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ComputeMetricsRequest.model_validate(
            {
                "base_metrics": _base_metrics(),
                "calculations": [
                    {
                        "formula": "median",
                        "output_key": "sales_median",
                    }
                ],
            }
        )

    assert any(error["loc"] == ("calculations", 0) for error in exc_info.value.errors())


def test_compute_metrics_request_rejects_duplicate_output_keys() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ComputeMetricsRequest.model_validate(
            {
                "base_metrics": _base_metrics(),
                "calculations": [
                    {
                        "formula": "delta",
                        "current_key": "sales_total_current",
                        "previous_key": "sales_total_previous",
                        "output_key": "dup_key",
                    },
                    {
                        "formula": "ratio",
                        "numerator_key": "sales_total_current",
                        "denominator_key": "order_count",
                        "output_key": "dup_key",
                    },
                ],
            }
        )

    assert "output_key values must be unique" in str(exc_info.value)


def test_compute_metrics_request_rejects_invalid_precision() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ComputeMetricsRequest.model_validate(
            {
                "base_metrics": _base_metrics(),
                "calculations": [
                    {
                        "formula": "delta",
                        "current_key": "sales_total_current",
                        "previous_key": "sales_total_previous",
                        "output_key": "sales_delta",
                    }
                ],
                "precision": 9,
            }
        )

    assert any(error["loc"] == ("precision",) for error in exc_info.value.errors())


def test_weighted_average_spec_rejects_mismatched_key_lengths() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ComputeMetricsRequest.model_validate(
            {
                "base_metrics": _base_metrics(),
                "calculations": [
                    {
                        "formula": "weighted_average",
                        "value_keys": ["source_a", "source_b"],
                        "weight_keys": ["weight_a"],
                        "output_key": "weighted_avg_sources",
                    }
                ],
            }
        )

    assert "same length" in str(exc_info.value)


def test_compute_metrics_request_rejects_unknown_extra_fields() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ComputeMetricsRequest.model_validate(
            {
                "base_metrics": _base_metrics(),
                "calculations": [
                    {
                        "formula": "ratio",
                        "numerator_key": "sales_total_current",
                        "denominator_key": "order_count",
                        "output_key": "sales_per_order",
                        "unexpected": "value",
                    }
                ],
            }
        )

    assert any(
        error["loc"] == ("calculations", 0, "ratio", "unexpected")
        and error["type"] == "extra_forbidden"
        for error in exc_info.value.errors()
    )


def test_compute_metrics_response_accepts_null_value_with_warning() -> None:
    response = ComputeMetricsResponse.model_validate(
        {
            "derived_metrics": [
                {
                    "key": "sales_percent_change",
                    "formula": "percent_change",
                    "value": None,
                    "inputs_used": {
                        "current": "12345.67",
                        "previous": "0",
                    },
                    "warnings": ["division_by_zero"],
                }
            ],
            "warnings": ["division_by_zero"],
        }
    )

    assert response.derived_metrics[0].value is None
    assert response.derived_metrics[0].formula is CalculationFormula.PERCENT_CHANGE
    assert response.warnings == [CalculationWarningCode.DIVISION_BY_ZERO]


def test_compute_metrics_request_rejects_blank_base_metric_key() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ComputeMetricsRequest.model_validate(
            {
                "base_metrics": {"": "123.45"},
                "calculations": [
                    {
                        "formula": "average",
                        "value_keys": ["source_a"],
                        "output_key": "avg_sources",
                    }
                ],
            }
        )

    assert "base_metrics keys must be non-empty strings" in str(exc_info.value)
