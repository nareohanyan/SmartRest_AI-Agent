"""Deterministic behavior tests for report tools."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time, timezone

import pytest

import app.agent.report_tools as report_tools
from app.agent.report_tools import (
    get_report_definition_tool,
    list_reports_tool,
    resolve_scope_tool,
    run_report_tool,
)
from app.core.config import get_settings
from app.reports import REPORT_CATALOG_ORDER
from app.schemas.analysis import DimensionName, MetricName
from app.schemas.reports import (
    ReportFilters,
    ReportMetric,
    ReportRequest,
    ReportResult,
    ReportType,
)
from app.schemas.tools import (
    AccessStatus,
    ExportMode,
    GetReportDefinitionRequest,
    ListReportsRequest,
    ResolveScopeRequest,
    RunReportRequest,
    RunReportResponse,
    ToolOperation,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _resolver_override(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resolution:
        source_system_id = 1
        canonical_profile_id = 1
        canonical_user_id = 1

    class _Resolver:
        def resolve(self, **_kwargs: object) -> _Resolution:
            return _Resolution()

    monkeypatch.setattr(report_tools, "get_canonical_identity_resolver", lambda: _Resolver())


@pytest.fixture(autouse=True)
def _smartrest_report_override(monkeypatch: pytest.MonkeyPatch) -> None:
    def _run_report(request: ReportRequest, *, profile_id: int) -> RunReportResponse:
        del profile_id
        generated_at = datetime.combine(
            request.filters.date_to,
            time.min,
            tzinfo=timezone.utc,
        )
        if request.report_id is ReportType.SALES_TOTAL:
            if request.filters.source is not None:
                raise ValueError("Source filter is not supported")
            metrics = [ReportMetric(label="sales_total", value=12345.67)]
        elif request.report_id is ReportType.SALES_BY_SOURCE:
            if request.filters.source == "glovo":
                raise ValueError("Unsupported source")
            source_values = {
                "in_store": 9876.54,
                "takeaway": 2469.13,
            }
            if request.filters.source is None:
                metrics = [
                    ReportMetric(label="in_store", value=source_values["in_store"]),
                    ReportMetric(label="takeaway", value=source_values["takeaway"]),
                ]
            else:
                source_value = source_values[request.filters.source]
                metrics = [
                    ReportMetric(label=request.filters.source, value=source_value)
                ]
        elif request.report_id is ReportType.ORDER_COUNT:
            metrics = [ReportMetric(label="order_count", value=345.0)]
        else:
            metrics = [ReportMetric(label="average_check", value=35.78)]

        return RunReportResponse(
            result=ReportResult(
                report_id=request.report_id,
                filters=request.filters,
                metrics=metrics,
                generated_at=generated_at,
            ),
            warnings=["smartrest_backend_live_data"],
        )

    monkeypatch.setattr(report_tools, "run_smartrest_report", _run_report)


def _identity_payload() -> dict[str, int | str]:
    return {
        "user_id": 123,
        "profile_id": 456,
        "profile_nick": "ChefNick",
    }


def test_resolve_scope_granted_returns_all_reports() -> None:
    request = ResolveScopeRequest.model_validate({**_identity_payload(), "metadata": {}})

    response = resolve_scope_tool(request)

    assert response.status is AccessStatus.GRANTED
    assert response.denial_reason is None
    assert response.allowed_report_ids == list(REPORT_CATALOG_ORDER)
    assert response.allowed_branch_ids == ["*"]
    assert response.allowed_export_modes == [ExportMode.CSV, ExportMode.XLSX, ExportMode.PDF]
    assert response.allowed_metric_ids == [metric.value for metric in MetricName]
    assert response.allowed_dimension_ids == [dimension.value for dimension in DimensionName]
    assert response.allowed_metrics == list(MetricName)
    assert response.allowed_dimensions == list(DimensionName)
    assert response.allowed_tool_operations == list(ToolOperation)


def test_resolve_scope_denies_when_identity_is_not_mapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Resolver:
        def resolve(self, **_kwargs: object) -> None:
            return None

    monkeypatch.setattr(report_tools, "get_canonical_identity_resolver", lambda: _Resolver())
    request = ResolveScopeRequest.model_validate({**_identity_payload(), "metadata": {}})

    response = resolve_scope_tool(request)

    assert response.status is AccessStatus.DENIED
    assert response.denial_reason == "identity_not_mapped"
    assert response.allowed_report_ids == []


def test_resolve_scope_parses_granular_permissions_from_metadata() -> None:
    request = ResolveScopeRequest.model_validate(
        {
            **_identity_payload(),
            "metadata": {
                "allow_metrics": "sales_total,order_count",
                "allow_dimensions": "source",
                "allow_branch_ids": "branch_1,branch_3",
                "allow_export_modes": "csv,xlsx",
                "allow_tool_operations": "fetch_breakdown,top_k",
            },
        }
    )

    response = resolve_scope_tool(request)

    assert response.allowed_branch_ids == ["branch_1", "branch_3"]
    assert response.allowed_export_modes == [ExportMode.CSV, ExportMode.XLSX]
    assert response.allowed_metric_ids == [
        MetricName.SALES_TOTAL.value,
        MetricName.ORDER_COUNT.value,
    ]
    assert response.allowed_dimension_ids == [DimensionName.SOURCE.value]
    assert response.allowed_metrics == [MetricName.SALES_TOTAL, MetricName.ORDER_COUNT]
    assert response.allowed_dimensions == [DimensionName.SOURCE]
    assert response.allowed_tool_operations == [
        ToolOperation.FETCH_BREAKDOWN,
        ToolOperation.TOP_K,
    ]


def test_resolve_scope_parses_id_level_permissions_from_metadata() -> None:
    request = ResolveScopeRequest.model_validate(
        {
            **_identity_payload(),
            "metadata": {
                "allow_metric_ids": "sales_total,completed_order_count",
                "allow_dimension_ids": "source,branch",
                "allow_tool_operations": "fetch_total_metric",
            },
        }
    )

    response = resolve_scope_tool(request)

    assert response.allowed_metric_ids == ["sales_total", "completed_order_count"]
    assert response.allowed_dimension_ids == ["source", "branch"]
    assert response.allowed_metrics == [
        MetricName.SALES_TOTAL,
        MetricName.COMPLETED_ORDER_COUNT,
    ]
    assert response.allowed_dimensions == [DimensionName.SOURCE, DimensionName.BRANCH]
    assert response.allowed_tool_operations == [ToolOperation.FETCH_TOTAL_METRIC]


def test_list_reports_respects_allowed_ids_and_stable_catalog_order() -> None:
    request = ListReportsRequest.model_validate(
        {
            **_identity_payload(),
            "allowed_report_ids": ["sales_by_source", "sales_total"],
        }
    )

    response = list_reports_tool(request)

    report_ids = [definition.report_id for definition in response.reports]
    assert report_ids == [ReportType.SALES_TOTAL, ReportType.SALES_BY_SOURCE]


def test_get_report_definition_returns_static_catalog_entry() -> None:
    request = GetReportDefinitionRequest.model_validate({"report_id": "sales_by_source"})

    response = get_report_definition_tool(request)

    assert response.definition.report_id is ReportType.SALES_BY_SOURCE
    assert "ordering source" in response.definition.description.lower()


def test_run_report_sales_total_is_deterministic_for_same_input() -> None:
    request = RunReportRequest.model_validate(
        {
            **_identity_payload(),
            "request": {
                "report_id": "sales_total",
                "filters": {"date_from": "2026-03-01", "date_to": "2026-03-07"},
            },
        }
    )

    response_1 = run_report_tool(request)
    response_2 = run_report_tool(request)

    assert response_1.model_dump() == response_2.model_dump()
    assert response_1.warnings == ["smartrest_backend_live_data"]
    assert response_1.result.metrics[0].label == "sales_total"
    assert response_1.result.generated_at == datetime.combine(
        date(2026, 3, 7),
        time.min,
        tzinfo=timezone.utc,
    )


def test_run_report_sales_by_source_without_filter_returns_all_sources() -> None:
    request = RunReportRequest(
        **_identity_payload(),
        request=ReportRequest(
            report_id=ReportType.SALES_BY_SOURCE,
            filters=ReportFilters(date_from=date(2026, 3, 1), date_to=date(2026, 3, 7)),
        ),
    )

    response = run_report_tool(request)

    metrics_map = {metric.label: metric.value for metric in response.result.metrics}
    assert set(metrics_map) == {"in_store", "takeaway"}


def test_run_report_sales_by_source_with_filter_returns_single_source() -> None:
    request = RunReportRequest(
        **_identity_payload(),
        request=ReportRequest(
            report_id=ReportType.SALES_BY_SOURCE,
            filters=ReportFilters(
                date_from=date(2026, 3, 1),
                date_to=date(2026, 3, 7),
                source="takeaway",
            ),
        ),
    )

    response = run_report_tool(request)

    assert len(response.result.metrics) == 1
    assert response.result.metrics[0].label == "takeaway"


def test_run_report_unknown_source_fails() -> None:
    request = RunReportRequest(
        **_identity_payload(),
        request=ReportRequest(
            report_id=ReportType.SALES_BY_SOURCE,
            filters=ReportFilters(
                date_from=date(2026, 3, 1),
                date_to=date(2026, 3, 7),
                source="glovo",
            ),
        ),
    )

    with pytest.raises(ValueError, match="Unsupported source"):
        run_report_tool(request)


def test_run_report_source_filter_not_supported_for_sales_total_fails() -> None:
    request = RunReportRequest(
        **_identity_payload(),
        request=ReportRequest(
            report_id=ReportType.SALES_TOTAL,
            filters=ReportFilters(
                date_from=date(2026, 3, 1),
                date_to=date(2026, 3, 7),
                source="glovo",
            ),
        ),
    )

    with pytest.raises(ValueError, match="Source filter is not supported"):
        run_report_tool(request)
