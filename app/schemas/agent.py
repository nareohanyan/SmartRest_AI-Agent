from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.analysis import AnalysisPlan
from app.schemas.base import SchemaModel
from app.schemas.calculations import CalculationWarningCode, DerivedMetric
from app.schemas.reports import ReportFilters, ReportType
from app.schemas.tools import (
    GetReportDefinitionResponse,
    ListReportsResponse,
    ResolveScopeRequest,
    ResolveScopeResponse,
    RunReportResponse,
)


class IntentType(str, Enum):
    GET_KPI = "get_kpi"
    BREAKDOWN_KPI = "breakdown_kpi"
    SMALLTALK = "smalltalk"
    NEEDS_CLARIFICATION = "needs_clarification"
    UNSUPPORTED_REQUEST = "unsupported_request"


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    ONBOARDING = "onboarding"
    CLARIFY = "clarify"
    REJECTED = "rejected"
    DENIED = "denied"
    FAILED = "failed"


class PlannerSource(str, Enum):
    DETERMINISTIC = "deterministic"
    LLM = "llm"
    FALLBACK = "fallback"


class PolicyRoute(str, Enum):
    PREPARE_LEGACY_REPORT = "prepare_legacy_report"
    RUN_COMPARISON = "run_comparison"
    RUN_RANKING = "run_ranking"
    RUN_TREND = "run_trend"
    SMALLTALK = "smalltalk"
    CLARIFY = "clarify"
    REJECT = "reject"
    SAFE_ANSWER = "safe_answer"


class ToolResponses(SchemaModel):
    resolve_scope: ResolveScopeResponse | None = None
    list_reports: ListReportsResponse | None = None
    get_report_definition: GetReportDefinitionResponse | None = None
    run_report: RunReportResponse | None = None


class AgentState(SchemaModel):
    thread_id: UUID
    run_id: UUID
    user_question: str = Field(min_length=1)
    scope_request: ResolveScopeRequest | None = None
    user_scope: ResolveScopeResponse | None = None
    intent: IntentType | None = None
    analysis_plan: AnalysisPlan | None = None
    plan_source: PlannerSource | None = None
    plan_confidence: float | None = None
    policy_route: PolicyRoute | None = None
    policy_reason: str | None = None
    selected_report_id: ReportType | None = None
    filters: ReportFilters | None = None
    needs_clarification: bool
    clarification_question: str | None = None
    tool_responses: ToolResponses = Field(default_factory=ToolResponses)
    analysis_artifacts: dict[str, Any] = Field(default_factory=dict)
    base_metrics: dict[str, Decimal] = Field(default_factory=dict)
    derived_metrics: list[DerivedMetric] = Field(default_factory=list)
    calc_warnings: list[CalculationWarningCode] = Field(default_factory=list)
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


class LLMErrorCategory(str, Enum):
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    RATE_LIMIT = "rate_limit"
    AUTHENTICATION = "authentication"
    BAD_REQUEST = "bad_request"
    SERVER = "server"
    UNKNOWN = "unknown"
