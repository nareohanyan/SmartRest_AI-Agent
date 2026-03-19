from __future__ import annotations

from datetime import date
from pathlib import Path

from app.reports.excel_backend import load_excel_orders, run_excel_report
from app.schemas.reports import ReportFilters, ReportRequest, ReportType

_EXCEL_PATH = Path("data/12.07.2024-27.02.2025.xlsx")
_SHEET_NAME = "Sheet1"
_FULL_RANGE = ReportFilters(date_from=date(2024, 7, 12), date_to=date(2025, 2, 27))


def test_load_excel_orders_maps_source_and_courier_columns() -> None:
    rows = load_excel_orders(file_path=_EXCEL_PATH, sheet_name=_SHEET_NAME)

    assert rows
    assert any(row.source for row in rows)
    assert any(row.courier for row in rows)


def test_run_excel_report_sales_total_uses_non_zero_amounts() -> None:
    response = run_excel_report(
        ReportRequest(report_id=ReportType.SALES_TOTAL, filters=_FULL_RANGE),
        file_path=_EXCEL_PATH,
        sheet_name=_SHEET_NAME,
    )

    assert response.result.metrics[0].label == "sales_total"
    assert response.result.metrics[0].value > 0


def test_run_excel_report_extended_scope_metrics_are_available() -> None:
    report_ids = (
        ReportType.SALES_BY_COURIER,
        ReportType.TOP_LOCATIONS,
        ReportType.TOP_CUSTOMERS,
        ReportType.REPEAT_CUSTOMER_RATE,
        ReportType.DELIVERY_FEE_ANALYTICS,
        ReportType.PAYMENT_COLLECTION,
        ReportType.OUTSTANDING_BALANCE,
        ReportType.DAILY_SALES_TREND,
        ReportType.DAILY_ORDER_TREND,
        ReportType.SALES_BY_WEEKDAY,
        ReportType.GROSS_PROFIT,
        ReportType.LOCATION_CONCENTRATION,
    )

    for report_id in report_ids:
        response = run_excel_report(
            ReportRequest(report_id=report_id, filters=_FULL_RANGE),
            file_path=_EXCEL_PATH,
            sheet_name=_SHEET_NAME,
        )
        assert response.result.metrics


def test_top_customers_uses_phone_identity_keys() -> None:
    response = run_excel_report(
        ReportRequest(report_id=ReportType.TOP_CUSTOMERS, filters=_FULL_RANGE),
        file_path=_EXCEL_PATH,
        sheet_name=_SHEET_NAME,
    )

    labels = [metric.label for metric in response.result.metrics]
    assert labels
    assert all(label.isdigit() for label in labels)
