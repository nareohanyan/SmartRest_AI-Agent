"""Deterministic report tool layer."""

from __future__ import annotations

from enum import Enum
from typing import TypeVar

from app.core.config import get_settings
from app.reports import (
    REPORT_CATALOG_ORDER,
    SMARTREST_BACKEND_FALLBACK_WARNING,
    SmartRestReportBackendUnsupportedError,
    get_report_definition,
    list_report_definitions,
    run_mock_report,
    run_smartrest_report,
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
from app.services.canonical_identity import get_canonical_identity_resolver

_MOCK_DENIAL_REASON = "mock_access_denied"
_IDENTITY_NOT_MAPPED_REASON = "identity_not_mapped"
_SCOPE_DB_UNAVAILABLE_REASON = "scope_db_unavailable"
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


def _parse_source_cloud_num(metadata: dict[str, str]) -> int | None:
    raw_value = metadata.get("source_cloud_num")
    if raw_value is None:
        return None
    try:
        return int(raw_value)
    except ValueError:
        return None


def _resolve_scope_from_mock(request: ResolveScopeRequest) -> ResolveScopeResponse:
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


def _resolve_scope_from_db(request: ResolveScopeRequest) -> ResolveScopeResponse:
    settings = get_settings()
    resolver = get_canonical_identity_resolver()
    source_server_name = request.metadata.get(
        "source_system",
        settings.sync_source_system_server_name,
    )
    source_cloud_num = (
        _parse_source_cloud_num(request.metadata)
        or settings.sync_source_system_cloud_num
    )
    resolution = resolver.resolve(
        user_id=request.user_id,
        profile_id=request.profile_id,
        profile_nick=request.profile_nick,
        source_server_name=source_server_name,
        source_cloud_num=source_cloud_num,
    )
    if resolution is None:
        return ResolveScopeResponse(
            status=AccessStatus.DENIED,
            allowed_report_ids=[],
            denial_reason=_IDENTITY_NOT_MAPPED_REASON,
        )

    return ResolveScopeResponse(
        status=AccessStatus.GRANTED,
        allowed_report_ids=list(REPORT_CATALOG_ORDER),
        source_system_id=resolution.source_system_id,
        canonical_profile_id=resolution.canonical_profile_id,
        canonical_user_id=resolution.canonical_user_id,
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


def resolve_scope_tool(request: ResolveScopeRequest) -> ResolveScopeResponse:
    """Resolve access scope from canonical DB identity with controlled fallback."""
    if request.metadata.get("access") == "deny":
        return ResolveScopeResponse(
            status=AccessStatus.DENIED,
            allowed_report_ids=[],
            denial_reason=_MOCK_DENIAL_REASON,
        )

    settings = get_settings()
    if settings.scope_backend_mode == "mock":
        return _resolve_scope_from_mock(request)

    try:
        return _resolve_scope_from_db(request)
    except Exception:
        if settings.scope_backend_mode == "db_strict":
            return ResolveScopeResponse(
                status=AccessStatus.DENIED,
                allowed_report_ids=[],
                denial_reason=_SCOPE_DB_UNAVAILABLE_REASON,
            )
        return _resolve_scope_from_mock(request)


def list_reports_tool(request: ListReportsRequest) -> ListReportsResponse:
    """Return report definitions visible in the resolved allowed report set."""
    return ListReportsResponse(reports=list_report_definitions(request.allowed_report_ids))


def get_report_definition_tool(
    request: GetReportDefinitionRequest,
) -> GetReportDefinitionResponse:
    """Return one report definition from the static report catalog."""
    return GetReportDefinitionResponse(definition=get_report_definition(request.report_id))


def run_report_tool(request: RunReportRequest) -> RunReportResponse:
    """Execute report from SmartRest DB backend with fallback to deterministic mock data."""
    settings = get_settings()
    if settings.report_backend_mode == "mock":
        return run_mock_report(request.request)

    try:
        return run_smartrest_report(request.request, profile_id=request.profile_id)
    except SmartRestReportBackendUnsupportedError:
        if settings.report_backend_mode == "db_strict":
            raise
    except Exception:
        if settings.report_backend_mode == "db_strict":
            raise

    fallback = run_mock_report(request.request)
    merged_warnings = list(fallback.warnings)
    if SMARTREST_BACKEND_FALLBACK_WARNING not in merged_warnings:
        merged_warnings.append(SMARTREST_BACKEND_FALLBACK_WARNING)
    return RunReportResponse(result=fallback.result, warnings=merged_warnings)
