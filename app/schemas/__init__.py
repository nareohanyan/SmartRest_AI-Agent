"""Typed schemas for the SmartRest agent boundaries."""

from app.schemas.agent import AgentState, IntentType, RunStatus, ToolResponses
from app.schemas.reports import (
    ReportDefinition,
    ReportFilterKey,
    ReportFilters,
    ReportMetric,
    ReportRequest,
    ReportResult,
    ReportType,
)
from app.schemas.tools import (
    AccessStatus,
    GetReportDefinitionRequest,
    GetReportDefinitionResponse,
    ListReportsRequest,
    ListReportsResponse,
    ResolveScopeRequest,
    ResolveScopeResponse,
    RunReportRequest,
    RunReportResponse,
)

__all__ = [
    "AccessStatus",
    "AgentState",
    "GetReportDefinitionRequest",
    "GetReportDefinitionResponse",
    "IntentType",
    "ListReportsRequest",
    "ListReportsResponse",
    "ReportDefinition",
    "ReportFilterKey",
    "ReportFilters",
    "ReportType",
    "ReportMetric",
    "ReportRequest",
    "ReportResult",
    "ResolveScopeRequest",
    "ResolveScopeResponse",
    "RunReportRequest",
    "RunReportResponse",
    "RunStatus",
    "ToolResponses",
]
