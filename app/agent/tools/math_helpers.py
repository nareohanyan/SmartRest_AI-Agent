from __future__ import annotations

from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Decimal,
    InvalidOperation,
)
from statistics import fmean

from app.schemas.calculations import CalculationRoundingMode

_ROUNDING_MODE_MAP: dict[CalculationRoundingMode, str] = {
    CalculationRoundingMode.HALF_UP: ROUND_HALF_UP,
    CalculationRoundingMode.HALF_EVEN: ROUND_HALF_EVEN,
    CalculationRoundingMode.DOWN: ROUND_DOWN,
    CalculationRoundingMode.UP: ROUND_UP,
}


class MathError(ValueError):
    """Raised when an internal numerical operation cannot be completed."""


def to_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MathError("value is not numeric") from exc


def quantize_decimal(
    value: Decimal,
    *,
    precision: int = 2,
    rounding_mode: CalculationRoundingMode = CalculationRoundingMode.HALF_UP,
) -> Decimal:
    quantizer = Decimal("1").scaleb(-precision)
    rounded = value.quantize(quantizer, rounding=_ROUNDING_MODE_MAP[rounding_mode])
    return rounded.copy_abs() if rounded.is_zero() else rounded


def safe_divide(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    return numerator / denominator


def mean_decimal(values: list[Decimal]) -> Decimal:
    if not values:
        raise MathError("values must not be empty")
    return to_decimal(fmean(float(value) for value in values))


def linear_regression_slope(y_values: list[Decimal]) -> Decimal:
    if len(y_values) < 2:
        raise MathError("at least two points are required")

    x_values = [Decimal(index) for index in range(len(y_values))]
    x_mean = sum(x_values, Decimal("0")) / Decimal(len(x_values))
    y_mean = sum(y_values, Decimal("0")) / Decimal(len(y_values))

    numerator = sum(
        ((x - x_mean) * (y - y_mean) for x, y in zip(x_values, y_values, strict=True)),
        Decimal("0"),
    )
    denominator = sum(((x - x_mean) ** 2 for x in x_values), Decimal("0"))
    if denominator == 0:
        raise MathError("cannot compute slope with zero variance in x")
    return numerator / denominator
