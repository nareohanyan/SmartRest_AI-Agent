from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum

from pydantic import Field, model_validator

from app.schemas.base import SchemaModel


class ReportType(str, Enum):
    SALES_TOTAL = "sales_total"
    ORDER_COUNT = "order_count"
    AVERAGE_CHECK = "average_check"
    SALES_BY_SOURCE = "sales_by_source"


class ReportFilterKey(str, Enum):
    DATE_FROM = "date_from"
    DATE_TO = "date_to"
    SOURCE = "source"


class ReportFilters(SchemaModel):
    date_from: date
    date_to: date
    source: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_date_range(self) -> ReportFilters:
        if self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        return self


class ReportRequest(SchemaModel):
    report_id: ReportType
    filters: ReportFilters


class ReportDefinition(SchemaModel):
    report_id: ReportType
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    required_filters: tuple[ReportFilterKey, ...] = (
        ReportFilterKey.DATE_FROM,
        ReportFilterKey.DATE_TO,
    )
    optional_filters: tuple[ReportFilterKey, ...] = ()

    @model_validator(mode="after")
    def validate_filter_contract(self) -> ReportDefinition:
        required = set(self.required_filters)
        optional = set(self.optional_filters)

        if ReportFilterKey.DATE_FROM not in required or ReportFilterKey.DATE_TO not in required:
            raise ValueError("required_filters must include date_from and date_to")

        overlap = required & optional
        if overlap:
            overlap_fields = ", ".join(sorted(field.value for field in overlap))
            raise ValueError(f"required_filters and optional_filters overlap: {overlap_fields}")

        return self


class ReportMetric(SchemaModel):
    label: str = Field(min_length=1)
    value: float


class ReportResult(SchemaModel):
    report_id: ReportType
    filters: ReportFilters
    metrics: list[ReportMetric] = Field(min_length=1)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
