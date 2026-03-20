from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from app.schemas.base import SchemaModel
from app.schemas.reports import (
    ReportDefinition,
    ReportFilterKey,
    ReportRequest,
    ReportResult,
    ReportType,
)


class AccessStatus(str, Enum):
    GRANTED = "granted"
    DENIED = "denied"


class ResolveScopeRequest(SchemaModel):
    user_id: int
    profile_id: int
    profile_nick: str = Field(min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)


class ResolveScopeResponse(SchemaModel):
    status: AccessStatus
    allowed_report_ids: list[ReportType]
    denial_reason: str | None = None

    @model_validator(mode="after")
    def validate_access_details(self) -> ResolveScopeResponse:
        if self.status is AccessStatus.DENIED and not self.denial_reason:
            raise ValueError("denial_reason is required when status is denied")

        if self.status is AccessStatus.GRANTED and self.denial_reason is not None:
            raise ValueError("denial_reason must be null when status is granted")

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


class ResolveFilterValueStatus(str, Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    UNSUPPORTED = "unsupported"


class ResolveFilterValueRequest(SchemaModel):
    report_id: ReportType
    filter_key: ReportFilterKey
    raw_value: str = Field(min_length=1)


class ResolveFilterValueResponse(SchemaModel):
    status: ResolveFilterValueStatus
    matched_value: str | None = None
    candidates: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_contract(self) -> ResolveFilterValueResponse:
        if self.status is ResolveFilterValueStatus.RESOLVED and self.matched_value is None:
            raise ValueError("matched_value is required when status=resolved")
        if self.status is not ResolveFilterValueStatus.RESOLVED and self.matched_value is not None:
            raise ValueError("matched_value must be null unless status=resolved")
        return self
