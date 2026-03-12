from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.reports import ReportFilters, ReportType
from app.schemas.tools import (
    GetReportDefinitionResponse,
    ListReportsResponse,
    ResolveScopeRequest,
    ResolveScopeResponse,
    RunReportResponse,
)


class _SchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntentType(str, Enum):
    GET_KPI = "get_kpi"
    BREAKDOWN_KPI = "breakdown_kpi"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED_REQUEST = "unsupported_request"


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    CLARIFY = "clarify"
    REJECTED = "rejected"
    DENIED = "denied"
    FAILED = "failed"


class ToolResponses(_SchemaModel):
    resolve_scope: ResolveScopeResponse | None = None
    list_reports: ListReportsResponse | None = None
    get_report_definition: GetReportDefinitionResponse | None = None
    run_report: RunReportResponse | None = None


class AgentState(_SchemaModel):
    thread_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    user_question: str = Field(min_length=1)
    scope_request: ResolveScopeRequest | None = None
    user_scope: ResolveScopeResponse | None = None
    intent: IntentType | None = None
    selected_report_id: ReportType | None = None
    filters: ReportFilters | None = None
    needs_clarification: bool
    clarification_question: str | None = None
    tool_responses: ToolResponses = Field(default_factory=ToolResponses)
    warnings: list[str] = Field(default_factory=list)
    final_answer: str | None = None
    status: RunStatus

    @model_validator(mode="after")
    def validate_clarification_fields(self) -> AgentState:
        if self.needs_clarification and not self.clarification_question:
            raise ValueError(
                "clarification_question is required when needs_clarification is true"
            )

        if self.status is RunStatus.CLARIFY and not self.needs_clarification:
            raise ValueError("status=clarify requires needs_clarification=true")

        return self
