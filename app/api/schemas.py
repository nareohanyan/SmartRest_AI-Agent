from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent import RunStatus
from app.schemas.reports import ReportFilters, ReportType


class _ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScopeRequestPayload(_ApiSchema):
    user_id: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    profile_nick: str = Field(min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)


class AgentRunRequest(_ApiSchema):
    thread_id: str = Field(min_length=1)
    user_question: str = Field(min_length=1)
    scope_request: ScopeRequestPayload


class AgentRunResponse(_ApiSchema):
    thread_id: str
    run_id: str
    status: RunStatus
    answer: str | None = None
    selected_report_id: ReportType | None = None
    applied_filters: ReportFilters | None = None
    warnings: list[str] = Field(default_factory=list)
    needs_clarification: bool
    clarification_question: str | None = None
