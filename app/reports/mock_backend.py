"""Deterministic mock report backend for Task 8."""

from __future__ import annotations

from datetime import datetime, time, timezone

from app.reports.filter_resolution import normalize_phone_value, resolve_filter_value_from_catalog
from app.schemas.reports import (
    ReportFilterKey,
    ReportFilters,
    ReportMetric,
    ReportRequest,
    ReportResult,
    ReportType,
)
from app.schemas.tools import (
    ResolveFilterValueRequest,
    ResolveFilterValueResponse,
    RunReportResponse,
)

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

_FILTER_CATALOGS: dict[str, dict[str, float]] = {
    "source": _SOURCE_METRICS,
    "courier": _COURIER_METRICS,
    "location": _LOCATION_METRICS,
    "phone_number": _CUSTOMER_METRICS,
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


def _normalize_text_filter(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = (
        value.strip()
        .lower()
        .replace("֊", "-")
        .replace("–", "-")
        .replace("—", "-")
    )
    normalized = " ".join(normalized.split())
    return normalized or None


def _normalize_phone_filter(value: str | None) -> str | None:
    return normalize_phone_value(value)


def _filter_fingerprint(filters: ReportFilters, *, exclude: set[str] | None = None) -> str:
    excluded = exclude or set()
    values = []
    if "source" not in excluded and filters.source is not None:
        values.append(_canonical_filter_value("source", filters.source) or filters.source)
    if "courier" not in excluded and filters.courier is not None:
        values.append(_canonical_filter_value("courier", filters.courier) or filters.courier)
    if "location" not in excluded and filters.location is not None:
        values.append(_canonical_filter_value("location", filters.location) or filters.location)
    if "phone_number" not in excluded and filters.phone_number is not None:
        values.append(
            _canonical_filter_value("phone_number", filters.phone_number) or filters.phone_number
        )
    return "|".join(value for value in values if value is not None)


def _filter_factor(fingerprint: str) -> float:
    if not fingerprint:
        return 1.0
    return 0.35 + ((sum(ord(ch) for ch in fingerprint) % 61) / 100)


def _scale_value(value: float, factor: float) -> float:
    return round(value * factor, 2)


def _scaled_metrics_map(metrics: dict[str, float], factor: float) -> list[ReportMetric]:
    return [
        ReportMetric(label=label, value=_scale_value(value, factor))
        for label, value in metrics.items()
    ]


def _validate_known_filter(
    *,
    filter_name: str,
    normalized_value: str | None,
) -> None:
    if normalized_value is None:
        return
    if normalized_value not in _FILTER_CATALOGS[filter_name]:
        raise ValueError(f"Unsupported {filter_name}: {normalized_value}")


def _canonical_filter_value(filter_name: str, raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    filter_key = ReportFilterKey(filter_name)
    resolution = resolve_filter_value_from_catalog(
        report_id=ReportType.SALES_TOTAL,
        filter_key=filter_key,
        raw_value=raw_value,
        catalog_values=sorted(_FILTER_CATALOGS[filter_name]),
    )
    if resolution.matched_value is not None:
        return resolution.matched_value
    if filter_name == "source":
        return _normalize_source(raw_value)
    if filter_name == "phone_number":
        return _normalize_phone_filter(raw_value)
    return _normalize_text_filter(raw_value)


def run_mock_report(request: ReportRequest) -> RunReportResponse:
    """Return deterministic mock report output for a report request."""
    report_id = request.report_id
    filters = request.filters
    normalized_source = _canonical_filter_value("source", filters.source)
    normalized_courier = _canonical_filter_value("courier", filters.courier)
    normalized_location = _canonical_filter_value("location", filters.location)
    normalized_phone_number = _canonical_filter_value("phone_number", filters.phone_number)
    filter_factor = _filter_factor(_filter_fingerprint(filters))

    _validate_known_filter(filter_name="source", normalized_value=normalized_source)
    _validate_known_filter(filter_name="courier", normalized_value=normalized_courier)
    _validate_known_filter(filter_name="location", normalized_value=normalized_location)
    _validate_known_filter(filter_name="phone_number", normalized_value=normalized_phone_number)

    if report_id is ReportType.SALES_TOTAL:
        metrics = [ReportMetric(label="sales_total", value=_scale_value(12345.67, filter_factor))]
    elif report_id is ReportType.ORDER_COUNT:
        if (
            normalized_source is None
            and normalized_courier is None
            and normalized_location is None
            and normalized_phone_number is None
        ):
            metrics = [ReportMetric(label="order_count", value=345.0)]
        else:
            filter_fingerprint = _filter_fingerprint(filters)
            deterministic_count = float(1 + (sum(ord(ch) for ch in filter_fingerprint) % 300))
            metrics = [ReportMetric(label="order_count", value=deterministic_count)]
    elif report_id is ReportType.AVERAGE_CHECK:
        metrics = [ReportMetric(label="average_check", value=_scale_value(35.78, filter_factor))]
    elif report_id is ReportType.SALES_BY_SOURCE:
        if normalized_source is not None:
            source_factor = _filter_factor(_filter_fingerprint(filters, exclude={"source"}))
            metrics = [
                ReportMetric(
                    label=normalized_source,
                    value=_scale_value(_SOURCE_METRICS[normalized_source], source_factor),
                )
            ]
        else:
            metrics = _scaled_metrics_map(_SOURCE_METRICS, filter_factor)
    elif report_id is ReportType.SALES_BY_COURIER:
        if normalized_courier is not None:
            courier_factor = _filter_factor(_filter_fingerprint(filters, exclude={"courier"}))
            metrics = [
                ReportMetric(
                    label=normalized_courier,
                    value=_scale_value(_COURIER_METRICS[normalized_courier], courier_factor),
                )
            ]
        else:
            metrics = _scaled_metrics_map(_COURIER_METRICS, filter_factor)
    elif report_id is ReportType.TOP_LOCATIONS:
        if normalized_location is not None:
            location_factor = _filter_factor(_filter_fingerprint(filters, exclude={"location"}))
            metrics = [
                ReportMetric(
                    label=normalized_location,
                    value=_scale_value(_LOCATION_METRICS[normalized_location], location_factor),
                )
            ]
        else:
            metrics = _scaled_metrics_map(_LOCATION_METRICS, filter_factor)
    elif report_id is ReportType.TOP_CUSTOMERS:
        if normalized_phone_number is not None:
            phone_factor = _filter_factor(_filter_fingerprint(filters, exclude={"phone_number"}))
            metrics = [
                ReportMetric(
                    label=normalized_phone_number,
                    value=_scale_value(_CUSTOMER_METRICS[normalized_phone_number], phone_factor),
                )
            ]
        else:
            metrics = _scaled_metrics_map(_CUSTOMER_METRICS, filter_factor)
    elif report_id is ReportType.REPEAT_CUSTOMER_RATE:
        metrics = [
            ReportMetric(
                label="repeat_customer_rate_percent",
                value=min(100.0, _scale_value(42.86, 0.6 + (filter_factor * 0.4))),
            ),
            ReportMetric(label="repeat_customer_count", value=_scale_value(150.0, filter_factor)),
        ]
    elif report_id is ReportType.DELIVERY_FEE_ANALYTICS:
        metrics = [
            ReportMetric(label="delivery_fee_total", value=_scale_value(7120.00, filter_factor)),
            ReportMetric(label="delivery_fee_average", value=_scale_value(20.64, filter_factor)),
        ]
    elif report_id is ReportType.PAYMENT_COLLECTION:
        metrics = [
            ReportMetric(label="invoiced_total", value=_scale_value(12650.00, filter_factor)),
            ReportMetric(label="paid_total", value=_scale_value(11840.00, filter_factor)),
            ReportMetric(
                label="collection_rate_percent",
                value=min(100.0, _scale_value(93.60, 0.8 + (filter_factor * 0.2))),
            ),
        ]
    elif report_id is ReportType.OUTSTANDING_BALANCE:
        metrics = [
            ReportMetric(
                label="outstanding_balance",
                value=_scale_value(810.00, filter_factor),
            )
        ]
    elif report_id is ReportType.DAILY_SALES_TREND:
        metrics = [
            ReportMetric(label=day, value=_scale_value(value, filter_factor))
            for day, value in _DAILY_SALES_METRICS.items()
        ]
    elif report_id is ReportType.DAILY_ORDER_TREND:
        metrics = [
            ReportMetric(label=day, value=_scale_value(value, filter_factor))
            for day, value in _DAILY_ORDER_METRICS.items()
        ]
    elif report_id is ReportType.SALES_BY_WEEKDAY:
        metrics = [
            ReportMetric(label=weekday, value=_scale_value(value, filter_factor))
            for weekday, value in _WEEKDAY_METRICS.items()
        ]
    elif report_id is ReportType.GROSS_PROFIT:
        metrics = [
            ReportMetric(label="gross_profit", value=_scale_value(4180.00, filter_factor)),
            ReportMetric(label="gross_margin_percent", value=_scale_value(33.04, filter_factor)),
        ]
    elif report_id is ReportType.LOCATION_CONCENTRATION:
        if normalized_location is not None:
            metrics = [
                ReportMetric(label="top_10_location_share_percent", value=100.0),
                ReportMetric(label="top_1_location_share_percent", value=100.0),
                ReportMetric(label="distinct_locations_count", value=1.0),
            ]
        else:
            metrics = [
                ReportMetric(
                    label="top_10_location_share_percent",
                    value=_scale_value(71.20, filter_factor),
                ),
                ReportMetric(
                    label="top_1_location_share_percent",
                    value=_scale_value(18.65, filter_factor),
                ),
                ReportMetric(
                    label="distinct_locations_count",
                    value=_scale_value(55.0, filter_factor),
                ),
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


def resolve_mock_filter_value(request: ResolveFilterValueRequest) -> ResolveFilterValueResponse:
    catalogs = {
        "source": sorted(_SOURCE_METRICS),
        "courier": sorted(_COURIER_METRICS),
        "location": sorted(_LOCATION_METRICS),
        "phone_number": sorted(_CUSTOMER_METRICS),
    }
    return resolve_filter_value_from_catalog(
        report_id=request.report_id,
        filter_key=request.filter_key,
        raw_value=request.raw_value,
        catalog_values=catalogs.get(request.filter_key.value, []),
    )
