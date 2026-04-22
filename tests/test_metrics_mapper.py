"""Unit tests for report->base-metrics mapping (C3)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.agent.metrics_mapper import map_report_response_to_base_metrics
from app.schemas.reports import ReportFilters, ReportMetric, ReportResult, ReportType
from app.schemas.tools import RunReportResponse


def _identity_payload() -> dict[str, int | str]:
    return {
        "user_id": 123,
        "profile_id": 456,
        "profile_nick": "ChefNick",
    }


def test_map_sales_total_report_to_base_metrics() -> None:
    response = RunReportResponse(
        result=ReportResult(
            report_id=ReportType.SALES_TOTAL,
            filters=ReportFilters(date_from=date(2026, 3, 1), date_to=date(2026, 3, 7)),
            metrics=[ReportMetric(label="sales_total", value=12345.67)],
        ),
        warnings=[],
    )

    mapped = map_report_response_to_base_metrics(response)

    assert mapped["day_count"] == Decimal("7")
    assert mapped["sales_total"] == Decimal("12345.67")


def test_map_sales_by_source_report_to_base_metrics_with_total() -> None:
    response = RunReportResponse(
        result=ReportResult(
            report_id=ReportType.SALES_BY_SOURCE,
            filters=ReportFilters(date_from=date(2026, 3, 1), date_to=date(2026, 3, 7)),
            metrics=[
                ReportMetric(label="takeaway", value=4100.0),
                ReportMetric(label="in_store", value=8245.67),
            ],
        ),
        warnings=[],
    )

    mapped = map_report_response_to_base_metrics(response)

    assert mapped["day_count"] == Decimal("7")
    assert mapped["source_takeaway_sales"] == Decimal("4100.0")
    assert mapped["source_in_store_sales"] == Decimal("8245.67")
    assert mapped["sales_total"] == Decimal("12345.67")


def test_map_sales_by_source_single_source_sets_sales_total_from_subset() -> None:
    response = RunReportResponse(
        result=ReportResult(
            report_id=ReportType.SALES_BY_SOURCE,
            filters=ReportFilters(
                date_from=date(2026, 3, 1),
                date_to=date(2026, 3, 7),
                source="takeaway",
            ),
            metrics=[ReportMetric(label="takeaway", value=4100.0)],
        ),
        warnings=[],
    )

    mapped = map_report_response_to_base_metrics(response)

    assert mapped["source_takeaway_sales"] == Decimal("4100.0")
    assert mapped["sales_total"] == Decimal("4100.0")


def test_map_report_response_rejects_duplicate_normalized_keys() -> None:
    response = RunReportResponse(
        result=ReportResult(
            report_id=ReportType.SALES_BY_SOURCE,
            filters=ReportFilters(date_from=date(2026, 3, 1), date_to=date(2026, 3, 7)),
            metrics=[
                ReportMetric(label="Glovo", value=10.0),
                ReportMetric(label="glovo!", value=20.0),
            ],
        ),
        warnings=[],
    )

    with pytest.raises(ValueError, match="Duplicate source metric key"):
        map_report_response_to_base_metrics(response)
