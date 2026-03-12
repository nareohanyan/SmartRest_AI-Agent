"""Deterministic mock report backend for Task 8."""

from __future__ import annotations

from datetime import datetime, time, timezone

from app.schemas.reports import ReportFilters, ReportMetric, ReportRequest, ReportResult, ReportType
from app.schemas.tools import RunReportResponse

MOCK_BACKEND_WARNING = "mock_backend_deterministic_data"

_SOURCE_METRICS: dict[str, float] = {
    "in_store": 5200.00,
    "glovo": 4100.00,
    "wolt": 2200.00,
    "takeaway": 845.67,
}


def _generated_at(filters: ReportFilters) -> datetime:
    """Use filter end-date as a deterministic generated_at value."""
    return datetime.combine(filters.date_to, time.min, tzinfo=timezone.utc)


def _normalize_source(source: str | None) -> str | None:
    if source is None:
        return None
    normalized = source.strip().lower()
    if not normalized:
        return None
    return normalized


def run_mock_report(request: ReportRequest) -> RunReportResponse:
    """Return deterministic mock report output for a report request."""
    report_id = request.report_id
    filters = request.filters
    normalized_source = _normalize_source(filters.source)

    if normalized_source is not None and normalized_source not in _SOURCE_METRICS:
        raise ValueError(f"Unsupported source: {normalized_source}")

    if normalized_source is not None and report_id is not ReportType.SALES_BY_SOURCE:
        raise ValueError(f"Source filter is not supported for report_id={report_id.value}")

    if report_id is ReportType.SALES_TOTAL:
        metrics = [ReportMetric(label="sales_total", value=12345.67)]
    elif report_id is ReportType.ORDER_COUNT:
        metrics = [ReportMetric(label="order_count", value=345.0)]
    elif report_id is ReportType.AVERAGE_CHECK:
        metrics = [ReportMetric(label="average_check", value=35.78)]
    elif report_id is ReportType.SALES_BY_SOURCE:
        if normalized_source is not None:
            metrics = [
                ReportMetric(
                    label=normalized_source,
                    value=_SOURCE_METRICS[normalized_source],
                )
            ]
        else:
            metrics = [
                ReportMetric(label=source, value=value)
                for source, value in _SOURCE_METRICS.items()
            ]
    else:
        raise ValueError(f"Unsupported report_id: {report_id.value}")

    result = ReportResult(
        report_id=report_id,
        filters=filters,
        metrics=metrics,
        generated_at=_generated_at(filters),
    )
    return RunReportResponse(result=result, warnings=[MOCK_BACKEND_WARNING])
