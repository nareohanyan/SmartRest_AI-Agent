from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, model_validator

from app.schemas.base import SchemaModel


class CalculationFormula(str, Enum):
    DELTA = "delta"
    PERCENT_CHANGE = "percent_change"
    RATIO = "ratio"
    SHARE_PERCENT = "share_percent"
    AVERAGE = "average"
    WEIGHTED_AVERAGE = "weighted_average"
    PER_DAY_RATE = "per_day_rate"


class CalculationWarningCode(str, Enum):
    MISSING_OPERAND = "missing_operand"
    DIVISION_BY_ZERO = "division_by_zero"
    INVALID_WEIGHT_SUM = "invalid_weight_sum"
    NON_NUMERIC_INPUT = "non_numeric_input"


class CalculationRoundingMode(str, Enum):
    HALF_UP = "half_up"
    HALF_EVEN = "half_even"
    DOWN = "down"
    UP = "up"


class _CalculationSpecBase(SchemaModel):
    output_key: str = Field(min_length=1)


class DeltaCalculationSpec(_CalculationSpecBase):
    formula: Literal["delta"] = "delta"
    current_key: str = Field(min_length=1)
    previous_key: str = Field(min_length=1)


class PercentChangeCalculationSpec(_CalculationSpecBase):
    formula: Literal["percent_change"] = "percent_change"
    current_key: str = Field(min_length=1)
    previous_key: str = Field(min_length=1)


class RatioCalculationSpec(_CalculationSpecBase):
    formula: Literal["ratio"] = "ratio"
    numerator_key: str = Field(min_length=1)
    denominator_key: str = Field(min_length=1)


class SharePercentCalculationSpec(_CalculationSpecBase):
    formula: Literal["share_percent"] = "share_percent"
    part_key: str = Field(min_length=1)
    total_key: str = Field(min_length=1)


class AverageCalculationSpec(_CalculationSpecBase):
    formula: Literal["average"] = "average"
    value_keys: list[str] = Field(min_length=1)


class WeightedAverageCalculationSpec(_CalculationSpecBase):
    formula: Literal["weighted_average"] = "weighted_average"
    value_keys: list[str] = Field(min_length=1)
    weight_keys: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_weight_dimensions(self) -> WeightedAverageCalculationSpec:
        if len(self.value_keys) != len(self.weight_keys):
            raise ValueError("value_keys and weight_keys must have the same length")
        return self


class PerDayRateCalculationSpec(_CalculationSpecBase):
    formula: Literal["per_day_rate"] = "per_day_rate"
    metric_key: str = Field(min_length=1)
    day_count_key: str = Field(min_length=1)


CalculationSpec: TypeAlias = Annotated[
    DeltaCalculationSpec
    | PercentChangeCalculationSpec
    | RatioCalculationSpec
    | SharePercentCalculationSpec
    | AverageCalculationSpec
    | WeightedAverageCalculationSpec
    | PerDayRateCalculationSpec,
    Field(discriminator="formula"),
]


class ComputeMetricsRequest(SchemaModel):
    base_metrics: dict[str, Decimal]
    calculations: list[CalculationSpec] = Field(min_length=1)
    precision: int = Field(default=2, ge=0, le=6)
    rounding_mode: CalculationRoundingMode = CalculationRoundingMode.HALF_UP

    @model_validator(mode="after")
    def validate_request_contract(self) -> ComputeMetricsRequest:
        invalid_metric_keys = [key for key in self.base_metrics if not key.strip()]
        if invalid_metric_keys:
            raise ValueError("base_metrics keys must be non-empty strings")

        output_keys = [calculation.output_key for calculation in self.calculations]
        if len(set(output_keys)) != len(output_keys):
            raise ValueError("calculation output_key values must be unique")

        return self


class DerivedMetric(SchemaModel):
    key: str = Field(min_length=1)
    formula: CalculationFormula
    value: Decimal | None = None
    inputs_used: dict[str, Decimal | list[Decimal] | None] = Field(default_factory=dict)
    warnings: list[CalculationWarningCode] = Field(default_factory=list)


class ComputeMetricsResponse(SchemaModel):
    derived_metrics: list[DerivedMetric] = Field(default_factory=list)
    warnings: list[CalculationWarningCode] = Field(default_factory=list)
