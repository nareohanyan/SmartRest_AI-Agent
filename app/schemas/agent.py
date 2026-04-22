from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.analysis import AnalysisPlan, LegacyReportTask, LegacyReportTaskResult
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
    RUN_MULTI_REPORT = "run_multi_report"
    RUN_BUSINESS_QUERY = "run_business_query"
    RUN_TOTAL = "run_total"
    RUN_COMPARISON = "run_comparison"
    RUN_RANKING = "run_ranking"
    RUN_TREND = "run_trend"
    SMALLTALK = "smalltalk"
    CLARIFY = "clarify"
    REJECT = "reject"
    SAFE_ANSWER = "safe_answer"


class ExecutionStepStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


class ExecutionStepType(str, Enum):
    TOOL = "tool"


class ExecutionTraceStep(SchemaModel):
    step_id: str = Field(min_length=1)
    step_type: ExecutionStepType = ExecutionStepType.TOOL
    status: ExecutionStepStatus
    input_ref: str | None = None
    output_ref: str | None = None
    duration_ms: float = Field(ge=0.0)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None


class ToolResponses(SchemaModel):
    resolve_scope: ResolveScopeResponse | None = None
    list_reports: ListReportsResponse | None = None
    get_report_definition: GetReportDefinitionResponse | None = None
    run_report: RunReportResponse | None = None


class AgentState(SchemaModel):
    chat_id: UUID
    run_id: UUID
    user_question: str = Field(min_length=1)
    scope_request: ResolveScopeRequest | None = None
    user_scope: ResolveScopeResponse | None = None
    intent: IntentType | None = None
    analysis_plan: AnalysisPlan | None = None
    legacy_tasks: list[LegacyReportTask] = Field(default_factory=list)
    legacy_task_results: list[LegacyReportTaskResult] = Field(default_factory=list)
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
    execution_trace: list[ExecutionTraceStep] = Field(default_factory=list)
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

        if self.status is RunStatus.ONBOARDING and self.needs_clarification:
            raise ValueError("status=onboarding requires needs_clarification=false")

        if self.status is RunStatus.ONBOARDING and self.clarification_question is not None:
            raise ValueError("status=onboarding requires clarification_question=null")

        return self


class LLMErrorCategory(str, Enum):
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    RATE_LIMIT = "rate_limit"
    AUTHENTICATION = "authentication"
    BAD_REQUEST = "bad_request"
    SERVER = "server"
    UNKNOWN = "unknown"
