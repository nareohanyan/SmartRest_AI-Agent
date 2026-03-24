from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from app.schemas.analysis import DimensionName, MetricName
from app.schemas.base import SchemaModel
from app.schemas.reports import ReportDefinition, ReportRequest, ReportResult, ReportType


class AccessStatus(str, Enum):
    GRANTED = "granted"
    DENIED = "denied"


class ToolOperation(str, Enum):
    RESOLVE_SCOPE = "resolve_scope"
    RUN_REPORT = "run_report"
    COMPUTE_SCALAR_METRICS = "compute_scalar_metrics"
    FETCH_TOTAL_METRIC = "fetch_total_metric"
    FETCH_BREAKDOWN = "fetch_breakdown"
    FETCH_TIMESERIES = "fetch_timeseries"
    ATTACH_BREAKDOWN_SHARE = "attach_breakdown_share"
    TOP_K = "top_k"
    BOTTOM_K = "bottom_k"
    MOVING_AVERAGE = "moving_average"
    TREND_SLOPE = "trend_slope"


class ResolveScopeRequest(SchemaModel):
    user_id: int
    profile_id: int
    profile_nick: str = Field(min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)


class ResolveScopeResponse(SchemaModel):
    status: AccessStatus
    allowed_report_ids: list[ReportType]
    allowed_metrics: list[MetricName] | None = None
    allowed_dimensions: list[DimensionName] | None = None
    allowed_tool_operations: list[ToolOperation] | None = None
    denial_reason: str | None = None

    @model_validator(mode="after")
    def validate_access_details(self) -> ResolveScopeResponse:
        if self.status is AccessStatus.DENIED and not self.denial_reason:
            raise ValueError("denial_reason is required when status is denied")

        if self.status is AccessStatus.GRANTED and self.denial_reason is not None:
            raise ValueError("denial_reason must be null when status is granted")

        if self.status is AccessStatus.GRANTED:
            if self.allowed_metrics is None:
                self.allowed_metrics = list(MetricName)
            if self.allowed_dimensions is None:
                self.allowed_dimensions = list(DimensionName)
            if self.allowed_tool_operations is None:
                self.allowed_tool_operations = list(ToolOperation)

        return self


class ListReportsRequest(SchemaModel):
    user_id: int
    profile_id: int
    profile_nick: str = Field(min_length=1)
    allowed_report_ids: list[ReportType]


class ListReportsResponse(SchemaModel):
    reports: list[ReportDefinition]


class GetReportDefinitionRequest(SchemaModel):
    report_id: ReportType


class GetReportDefinitionResponse(SchemaModel):
    definition: ReportDefinition


class RunReportRequest(SchemaModel):
    user_id: int
    profile_id: int
    profile_nick: str = Field(min_length=1)
    request: ReportRequest


class RunReportResponse(SchemaModel):
    result: ReportResult
    warnings: list[str] = Field(default_factory=list)
