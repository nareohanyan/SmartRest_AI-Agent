from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class SignedAuthPayload(_ApiSchema):
    profile_nick: str = Field(min_length=1)
    user_id: int
    profile_id: int
    current_timestamp: int
    token: str = Field(min_length=64, max_length=64)


class AgentRunRequest(_ApiSchema):
    chat_id: UUID
    user_question: str = Field(min_length=1)
    auth: SignedAuthPayload
    scope_request: ScopeRequestPayload

    @model_validator(mode="after")
    def validate_auth_matches_scope_identity(self) -> AgentRunRequest:
        if self.auth.profile_nick != self.scope_request.profile_nick:
            raise ValueError("auth.profile_nick must match scope_request.profile_nick")
        if self.auth.user_id != self.scope_request.user_id:
            raise ValueError("auth.user_id must match scope_request.user_id")
        if self.auth.profile_id != self.scope_request.profile_id:
            raise ValueError("auth.profile_id must match scope_request.profile_id")
        return self


class AgentRunResponse(_ApiSchema):
    chat_id: UUID
    run_id: UUID
    status: RunStatus
    answer: str | None = None
    selected_report_id: ReportType | None = None
    applied_filters: ReportFilters | None = None
    warnings: list[str] = Field(default_factory=list)
    needs_clarification: bool
    clarification_question: str | None = None
