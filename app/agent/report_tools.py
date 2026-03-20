"""Deterministic report tool layer."""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.reports import (
    REPORT_CATALOG_ORDER,
    get_report_definition,
    list_report_definitions,
    run_mock_report,
)
from app.reports.excel_backend import resolve_excel_filter_value, run_excel_report
from app.reports.mock_backend import resolve_mock_filter_value
from app.schemas.tools import (
    AccessStatus,
    GetReportDefinitionRequest,
    GetReportDefinitionResponse,
    ListReportsRequest,
    ListReportsResponse,
    ResolveFilterValueRequest,
    ResolveFilterValueResponse,
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
    settings = get_settings()
    excel_path = settings.excel_report_file_path
    if excel_path and excel_path.strip():
        path = Path(excel_path)
        if not path.exists():
            raise ValueError(f"Excel report file not found: {path}")
        return run_excel_report(
            request.request,
            file_path=path,
            sheet_name=settings.excel_report_sheet_name,
        )
    return run_mock_report(request.request)


def resolve_filter_value_tool(request: ResolveFilterValueRequest) -> ResolveFilterValueResponse:
    """Resolve a raw filter mention against backend-backed canonical values."""
    settings = get_settings()
    excel_path = settings.excel_report_file_path
    if excel_path and excel_path.strip():
        path = Path(excel_path)
        if not path.exists():
            raise ValueError(f"Excel report file not found: {path}")
        return resolve_excel_filter_value(
            request,
            file_path=path,
            sheet_name=settings.excel_report_sheet_name,
        )
    return resolve_mock_filter_value(request)
