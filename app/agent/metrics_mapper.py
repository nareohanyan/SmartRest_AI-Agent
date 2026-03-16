"""Map report outputs into canonical base metrics for deterministic calculations."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.schemas.reports import ReportType
from app.schemas.tools import RunReportResponse

_NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9]+")


def _to_decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Report metric value is not numeric.") from exc


def _normalize_key(raw_key: str) -> str:
    normalized = _NON_ALNUM_PATTERN.sub("_", raw_key.strip().lower()).strip("_")
    if not normalized:
        raise ValueError("Report metric key cannot be empty after normalization.")
    return normalized


def map_report_response_to_base_metrics(run_response: RunReportResponse) -> dict[str, Decimal]:
    """Convert deterministic report output to canonical base metric IDs."""
    result = run_response.result
    report_id = result.report_id
    filters = result.filters
    base_metrics: dict[str, Decimal] = {}

    day_count = (filters.date_to - filters.date_from).days + 1
    if day_count <= 0:
        raise ValueError("Report date range produced invalid day_count.")
    base_metrics["day_count"] = Decimal(day_count)

    if report_id is ReportType.SALES_BY_SOURCE:
        sales_total = Decimal("0")
        for metric in result.metrics:
            source_name = _normalize_key(metric.label)
            metric_key = f"source_{source_name}_sales"
            if metric_key in base_metrics:
                raise ValueError(f"Duplicate source metric key: {metric_key}")

            value = _to_decimal(metric.value)
            base_metrics[metric_key] = value
            sales_total += value

        base_metrics["sales_total"] = sales_total
        return base_metrics

    for metric in result.metrics:
        metric_key = _normalize_key(metric.label)
        if metric_key in base_metrics:
            raise ValueError(f"Duplicate base metric key: {metric_key}")

        base_metrics[metric_key] = _to_decimal(metric.value)

    return base_metrics
