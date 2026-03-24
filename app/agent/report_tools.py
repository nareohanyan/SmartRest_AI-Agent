"""Deterministic report tool layer."""

from __future__ import annotations

from enum import Enum
from typing import TypeVar

from app.reports import (
    REPORT_CATALOG_ORDER,
    get_report_definition,
    list_report_definitions,
    run_mock_report,
)
from app.schemas.analysis import DimensionName, MetricName
from app.schemas.tools import (
    AccessStatus,
    ExportMode,
    GetReportDefinitionRequest,
    GetReportDefinitionResponse,
    ListReportsRequest,
    ListReportsResponse,
    ResolveScopeRequest,
    ResolveScopeResponse,
    RunReportRequest,
    RunReportResponse,
    ToolOperation,
)

_MOCK_DENIAL_REASON = "mock_access_denied"
_CSV_SEPARATOR = ","
_EnumT = TypeVar("_EnumT", bound=Enum)


def _parse_enum_csv(
    *,
    metadata: dict[str, str],
    key: str,
    enum_type: type[_EnumT],
) -> list[_EnumT] | None:
    raw_value = metadata.get(key)
    if raw_value is None:
        return None

    tokens = [token.strip() for token in raw_value.split(_CSV_SEPARATOR) if token.strip()]
    if not tokens:
        return []

    return [enum_type(token) for token in tokens]


def _parse_csv(
    *,
    metadata: dict[str, str],
    key: str,
) -> list[str] | None:
    raw_value = metadata.get(key)
    if raw_value is None:
        return None
    return [token.strip() for token in raw_value.split(_CSV_SEPARATOR) if token.strip()]


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
        allowed_branch_ids=_parse_csv(metadata=request.metadata, key="allow_branch_ids"),
        allowed_export_modes=_parse_enum_csv(
            metadata=request.metadata,
            key="allow_export_modes",
            enum_type=ExportMode,
        ),
        allowed_metric_ids=(
            _parse_csv(metadata=request.metadata, key="allow_metric_ids")
            or _parse_csv(metadata=request.metadata, key="allow_metrics")
        ),
        allowed_dimension_ids=(
            _parse_csv(metadata=request.metadata, key="allow_dimension_ids")
            or _parse_csv(metadata=request.metadata, key="allow_dimensions")
        ),
        allowed_metrics=_parse_enum_csv(
            metadata=request.metadata,
            key="allow_metrics",
            enum_type=MetricName,
        ),
        allowed_dimensions=_parse_enum_csv(
            metadata=request.metadata,
            key="allow_dimensions",
            enum_type=DimensionName,
        ),
        allowed_tool_operations=_parse_enum_csv(
            metadata=request.metadata,
            key="allow_tool_operations",
            enum_type=ToolOperation,
        ),
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
