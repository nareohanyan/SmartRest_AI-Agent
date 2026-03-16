"""Deterministic report tool layer."""

from __future__ import annotations

from app.reports import (
    REPORT_CATALOG_ORDER,
    get_report_definition,
    list_report_definitions,
    run_mock_report,
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

_MOCK_DENIAL_REASON = "mock_access_denied"


def resolve_scope_tool(request: ResolveScopeRequest) -> ResolveScopeResponse:
    """Resolve access scope deterministically from identity and optional metadata."""
    if request.metadata.get("access") == "deny":
        return ResolveScopeResponse(
            status=AccessStatus.DENIED,
            allowed_report_ids=[],
            denial_reason=_MOCK_DENIAL_REASON,
        )

    return ResolveScopeResponse(
        status=AccessStatus.GRANTED,
        allowed_report_ids=list(REPORT_CATALOG_ORDER),
        denial_reason=None,
    )


def list_reports_tool(request: ListReportsRequest) -> ListReportsResponse:
    """Return report definitions visible in the resolved allowed report set."""
    return ListReportsResponse(reports=list_report_definitions(request.allowed_report_ids))


def get_report_definition_tool(
    request: GetReportDefinitionRequest,
) -> GetReportDefinitionResponse:
    """Return one report definition from the static report catalog."""
    return GetReportDefinitionResponse(definition=get_report_definition(request.report_id))


def run_report_tool(request: RunReportRequest) -> RunReportResponse:
    """Execute a deterministic mock report using validated request payload."""
    return run_mock_report(request.request)

