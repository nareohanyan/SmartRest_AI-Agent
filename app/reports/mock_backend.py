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

_COURIER_METRICS: dict[str, float] = {
    "azat": 3920.00,
    "edgar": 2840.00,
    "erik": 2450.00,
    "yandex": 2140.00,
}

_LOCATION_METRICS: dict[str, float] = {
    "kasakh_andraniki_29": 3820.00,
    "bagratunyats_18": 2490.00,
    "droi_6_48": 1950.00,
    "shiraki_70_2": 1710.00,
    "aharonyan_18_5": 1275.00,
}

_CUSTOMER_METRICS: dict[str, float] = {
    "094727202": 3170.00,
    "093558111": 2815.00,
    "098123456": 2240.00,
    "091765432": 1940.00,
    "055010203": 1520.00,
}

_WEEKDAY_METRICS: dict[str, float] = {
    "monday": 1600.00,
    "tuesday": 1700.00,
    "wednesday": 1800.00,
    "thursday": 1750.00,
    "friday": 2100.00,
    "saturday": 2300.00,
    "sunday": 2045.67,
}

_DAILY_SALES_METRICS: dict[str, float] = {
    "2026-03-01": 1650.00,
    "2026-03-02": 1715.67,
    "2026-03-03": 1775.00,
    "2026-03-04": 1680.00,
    "2026-03-05": 1810.00,
    "2026-03-06": 1865.00,
    "2026-03-07": 1850.00,
}

_DAILY_ORDER_METRICS: dict[str, float] = {
    "2026-03-01": 48.0,
    "2026-03-02": 50.0,
    "2026-03-03": 53.0,
    "2026-03-04": 47.0,
    "2026-03-05": 55.0,
    "2026-03-06": 58.0,
    "2026-03-07": 55.0,
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
    elif report_id is ReportType.SALES_BY_COURIER:
        metrics = [
            ReportMetric(label=courier, value=value)
            for courier, value in _COURIER_METRICS.items()
        ]
    elif report_id is ReportType.TOP_LOCATIONS:
        metrics = [
            ReportMetric(label=location, value=value)
            for location, value in _LOCATION_METRICS.items()
        ]
    elif report_id is ReportType.TOP_CUSTOMERS:
        metrics = [
            ReportMetric(label=customer, value=value)
            for customer, value in _CUSTOMER_METRICS.items()
        ]
    elif report_id is ReportType.REPEAT_CUSTOMER_RATE:
        metrics = [
            ReportMetric(label="repeat_customer_rate_percent", value=42.86),
            ReportMetric(label="repeat_customer_count", value=150.0),
        ]
    elif report_id is ReportType.DELIVERY_FEE_ANALYTICS:
        metrics = [
            ReportMetric(label="delivery_fee_total", value=7120.00),
            ReportMetric(label="delivery_fee_average", value=20.64),
        ]
    elif report_id is ReportType.PAYMENT_COLLECTION:
        metrics = [
            ReportMetric(label="invoiced_total", value=12650.00),
            ReportMetric(label="paid_total", value=11840.00),
            ReportMetric(label="collection_rate_percent", value=93.60),
        ]
    elif report_id is ReportType.OUTSTANDING_BALANCE:
        metrics = [ReportMetric(label="outstanding_balance", value=810.00)]
    elif report_id is ReportType.DAILY_SALES_TREND:
        metrics = [
            ReportMetric(label=day, value=value)
            for day, value in _DAILY_SALES_METRICS.items()
        ]
    elif report_id is ReportType.DAILY_ORDER_TREND:
        metrics = [
            ReportMetric(label=day, value=value)
            for day, value in _DAILY_ORDER_METRICS.items()
        ]
    elif report_id is ReportType.SALES_BY_WEEKDAY:
        metrics = [
            ReportMetric(label=weekday, value=value)
            for weekday, value in _WEEKDAY_METRICS.items()
        ]
    elif report_id is ReportType.GROSS_PROFIT:
        metrics = [
            ReportMetric(label="gross_profit", value=4180.00),
            ReportMetric(label="gross_margin_percent", value=33.04),
        ]
    elif report_id is ReportType.LOCATION_CONCENTRATION:
        metrics = [
            ReportMetric(label="top_10_location_share_percent", value=71.20),
            ReportMetric(label="top_1_location_share_percent", value=18.65),
            ReportMetric(label="distinct_locations_count", value=55.0),
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
