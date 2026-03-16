"""Deterministic calculation tool layer."""

from __future__ import annotations

from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Decimal,
    InvalidOperation,
)

from app.schemas.calculations import (
    AverageCalculationSpec,
    CalculationFormula,
    CalculationRoundingMode,
    CalculationWarningCode,
    ComputeMetricsRequest,
    ComputeMetricsResponse,
    DeltaCalculationSpec,
    DerivedMetric,
    PercentChangeCalculationSpec,
    PerDayRateCalculationSpec,
    RatioCalculationSpec,
    SharePercentCalculationSpec,
    WeightedAverageCalculationSpec,
)

_ROUNDING_MODE_MAP: dict[CalculationRoundingMode, str] = {
    CalculationRoundingMode.HALF_UP: ROUND_HALF_UP,
    CalculationRoundingMode.HALF_EVEN: ROUND_HALF_EVEN,
    CalculationRoundingMode.DOWN: ROUND_DOWN,
    CalculationRoundingMode.UP: ROUND_UP,
}


def _append_warning(
    warning_list: list[CalculationWarningCode], warning: CalculationWarningCode
) -> None:
    if warning not in warning_list:
        warning_list.append(warning)


def _to_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value

    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("non_decimal_value") from exc


def _resolve_operand(
    metrics: dict[str, Decimal],
    key: str,
    warnings: list[CalculationWarningCode],
) -> Decimal | None:
    if key not in metrics:
        _append_warning(warnings, CalculationWarningCode.MISSING_OPERAND)
        return None

    try:
        return _to_decimal(metrics[key])
    except ValueError:
        _append_warning(warnings, CalculationWarningCode.NON_NUMERIC_INPUT)
        return None


def _quantize_output(
    value: Decimal,
    precision: int,
    rounding_mode: CalculationRoundingMode,
) -> Decimal:
    quantizer = Decimal("1").scaleb(-precision)
    rounded = value.quantize(quantizer, rounding=_ROUNDING_MODE_MAP[rounding_mode])
    return rounded.copy_abs() if rounded.is_zero() else rounded


def _compute_delta(
    metrics: dict[str, Decimal],
    spec: DeltaCalculationSpec,
    warnings: list[CalculationWarningCode],
) -> tuple[Decimal | None, dict[str, Decimal | list[Decimal] | None]]:
    current = _resolve_operand(metrics, spec.current_key, warnings)
    previous = _resolve_operand(metrics, spec.previous_key, warnings)
    inputs_used: dict[str, Decimal | list[Decimal] | None] = {
        "current": current,
        "previous": previous,
    }
    if current is None or previous is None:
        return None, inputs_used
    return current - previous, inputs_used


def _compute_percent_change(
    metrics: dict[str, Decimal],
    spec: PercentChangeCalculationSpec,
    warnings: list[CalculationWarningCode],
) -> tuple[Decimal | None, dict[str, Decimal | list[Decimal] | None]]:
    current = _resolve_operand(metrics, spec.current_key, warnings)
    previous = _resolve_operand(metrics, spec.previous_key, warnings)
    inputs_used: dict[str, Decimal | list[Decimal] | None] = {
        "current": current,
        "previous": previous,
    }
    if current is None or previous is None:
        return None, inputs_used

    if previous == 0:
        _append_warning(warnings, CalculationWarningCode.DIVISION_BY_ZERO)
        return None, inputs_used

    return ((current - previous) / previous) * Decimal("100"), inputs_used


def _compute_ratio(
    metrics: dict[str, Decimal],
    spec: RatioCalculationSpec,
    warnings: list[CalculationWarningCode],
) -> tuple[Decimal | None, dict[str, Decimal | list[Decimal] | None]]:
    numerator = _resolve_operand(metrics, spec.numerator_key, warnings)
    denominator = _resolve_operand(metrics, spec.denominator_key, warnings)
    inputs_used: dict[str, Decimal | list[Decimal] | None] = {
        "numerator": numerator,
        "denominator": denominator,
    }
    if numerator is None or denominator is None:
        return None, inputs_used

    if denominator == 0:
        _append_warning(warnings, CalculationWarningCode.DIVISION_BY_ZERO)
        return None, inputs_used

    return numerator / denominator, inputs_used


def _compute_share_percent(
    metrics: dict[str, Decimal],
    spec: SharePercentCalculationSpec,
    warnings: list[CalculationWarningCode],
) -> tuple[Decimal | None, dict[str, Decimal | list[Decimal] | None]]:
    part = _resolve_operand(metrics, spec.part_key, warnings)
    total = _resolve_operand(metrics, spec.total_key, warnings)
    inputs_used: dict[str, Decimal | list[Decimal] | None] = {
        "part": part,
        "total": total,
    }
    if part is None or total is None:
        return None, inputs_used

    if total == 0:
        _append_warning(warnings, CalculationWarningCode.DIVISION_BY_ZERO)
        return None, inputs_used

    return (part / total) * Decimal("100"), inputs_used


def _compute_average(
    metrics: dict[str, Decimal],
    spec: AverageCalculationSpec,
    warnings: list[CalculationWarningCode],
) -> tuple[Decimal | None, dict[str, Decimal | list[Decimal] | None]]:
    values: list[Decimal] = []
    missing_or_invalid = False
    for key in spec.value_keys:
        value = _resolve_operand(metrics, key, warnings)
        if value is None:
            missing_or_invalid = True
            continue
        values.append(value)

    inputs_used: dict[str, Decimal | list[Decimal] | None] = {
        "values": values if not missing_or_invalid else None
    }
    if missing_or_invalid or not values:
        return None, inputs_used

    return sum(values, Decimal("0")) / Decimal(len(values)), inputs_used


def _compute_weighted_average(
    metrics: dict[str, Decimal],
    spec: WeightedAverageCalculationSpec,
    warnings: list[CalculationWarningCode],
) -> tuple[Decimal | None, dict[str, Decimal | list[Decimal] | None]]:
    values: list[Decimal] = []
    weights: list[Decimal] = []
    missing_or_invalid = False

    for value_key in spec.value_keys:
        value = _resolve_operand(metrics, value_key, warnings)
        if value is None:
            missing_or_invalid = True
            continue
        values.append(value)

    for weight_key in spec.weight_keys:
        weight = _resolve_operand(metrics, weight_key, warnings)
        if weight is None:
            missing_or_invalid = True
            continue
        weights.append(weight)

    inputs_used: dict[str, Decimal | list[Decimal] | None] = {
        "values": values if not missing_or_invalid else None,
        "weights": weights if not missing_or_invalid else None,
    }
    if missing_or_invalid or not values or not weights:
        return None, inputs_used

    weight_sum = sum(weights, Decimal("0"))
    if weight_sum == 0:
        _append_warning(warnings, CalculationWarningCode.INVALID_WEIGHT_SUM)
        return None, inputs_used

    weighted_sum = sum(
        (value * weight for value, weight in zip(values, weights)),
        Decimal("0"),
    )
    return weighted_sum / weight_sum, inputs_used


def _compute_per_day_rate(
    metrics: dict[str, Decimal],
    spec: PerDayRateCalculationSpec,
    warnings: list[CalculationWarningCode],
) -> tuple[Decimal | None, dict[str, Decimal | list[Decimal] | None]]:
    metric = _resolve_operand(metrics, spec.metric_key, warnings)
    day_count = _resolve_operand(metrics, spec.day_count_key, warnings)
    inputs_used: dict[str, Decimal | list[Decimal] | None] = {
        "metric": metric,
        "day_count": day_count,
    }
    if metric is None or day_count is None:
        return None, inputs_used

    if day_count == 0:
        _append_warning(warnings, CalculationWarningCode.DIVISION_BY_ZERO)
        return None, inputs_used

    return metric / day_count, inputs_used


def compute_metrics_tool(request: ComputeMetricsRequest) -> ComputeMetricsResponse:
    """Compute deterministic derived metrics from validated base metrics."""
    derived_metrics: list[DerivedMetric] = []
    aggregated_warnings: list[CalculationWarningCode] = []

    for calculation in request.calculations:
        local_warnings: list[CalculationWarningCode] = []
        value: Decimal | None
        inputs_used: dict[str, Decimal | list[Decimal] | None]

        if isinstance(calculation, DeltaCalculationSpec):
            value, inputs_used = _compute_delta(
                request.base_metrics, calculation, local_warnings
            )
        elif isinstance(calculation, PercentChangeCalculationSpec):
            value, inputs_used = _compute_percent_change(
                request.base_metrics, calculation, local_warnings
            )
        elif isinstance(calculation, RatioCalculationSpec):
            value, inputs_used = _compute_ratio(
                request.base_metrics, calculation, local_warnings
            )
        elif isinstance(calculation, SharePercentCalculationSpec):
            value, inputs_used = _compute_share_percent(
                request.base_metrics, calculation, local_warnings
            )
        elif isinstance(calculation, AverageCalculationSpec):
            value, inputs_used = _compute_average(
                request.base_metrics, calculation, local_warnings
            )
        elif isinstance(calculation, WeightedAverageCalculationSpec):
            value, inputs_used = _compute_weighted_average(
                request.base_metrics, calculation, local_warnings
            )
        elif isinstance(calculation, PerDayRateCalculationSpec):
            value, inputs_used = _compute_per_day_rate(
                request.base_metrics, calculation, local_warnings
            )
        else:
            raise ValueError(f"Unsupported calculation formula: {calculation.formula}")

        if value is not None:
            value = _quantize_output(value, request.precision, request.rounding_mode)

        for warning in local_warnings:
            _append_warning(aggregated_warnings, warning)

        derived_metrics.append(
            DerivedMetric(
                key=calculation.output_key,
                formula=CalculationFormula(calculation.formula),
                value=value,
                inputs_used=inputs_used,
                warnings=local_warnings,
            )
        )

    return ComputeMetricsResponse(
        derived_metrics=derived_metrics,
        warnings=aggregated_warnings,
    )

