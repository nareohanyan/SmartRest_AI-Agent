from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.reports import ReportDefinition, ReportRequest, ReportResult, ReportType


class _SchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccessStatus(str, Enum):
    GRANTED = "granted"
    DENIED = "denied"


class ResolveScopeRequest(_SchemaModel):
    user_id: str = Field(min_length=1)
    org_id: str = Field(min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)


class ResolveScopeResponse(_SchemaModel):
    status: AccessStatus
    scope_id: str = Field(min_length=1)
    allowed_report_ids: list[ReportType]
    denial_reason: str | None = None

    @model_validator(mode="after")
    def validate_access_details(self) -> ResolveScopeResponse:
        if self.status is AccessStatus.DENIED and not self.denial_reason:
            raise ValueError("denial_reason is required when status is denied")

        if self.status is AccessStatus.GRANTED and self.denial_reason is not None:
            raise ValueError("denial_reason must be null when status is granted")

        return self


class ListReportsRequest(_SchemaModel):
    scope_id: str = Field(min_length=1)
    allowed_report_ids: list[ReportType]


class ListReportsResponse(_SchemaModel):
    reports: list[ReportDefinition]


class GetReportDefinitionRequest(_SchemaModel):
    report_id: ReportType


class GetReportDefinitionResponse(_SchemaModel):
    definition: ReportDefinition


class RunReportRequest(_SchemaModel):
    scope_id: str = Field(min_length=1)
    request: ReportRequest


class RunReportResponse(_SchemaModel):
    result: ReportResult
    warnings: list[str] = Field(default_factory=list)
