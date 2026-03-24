from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent import RunStatus
from app.schemas.reports import ReportFilters, ReportType
from app.schemas.tools import ExportMode


class _ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScopeRequestPayload(_ApiSchema):
    user_id: int
    profile_id: int
    profile_nick: str = Field(min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)
    requested_branch_ids: list[str] | None = None
    requested_export_mode: ExportMode | None = None


class AgentRunRequest(_ApiSchema):
    thread_id: UUID
    user_question: str = Field(min_length=1)
    scope_request: ScopeRequestPayload


class AgentRunResponse(_ApiSchema):
    thread_id: UUID
    run_id: UUID
    status: RunStatus
    answer: str | None = None
    selected_report_id: ReportType | None = None
    applied_filters: ReportFilters | None = None
    warnings: list[str] = Field(default_factory=list)
    needs_clarification: bool
    clarification_question: str | None = None
