from __future__ import annotations

from datetime import date
from pathlib import Path

from app.reports.excel_backend import (
    load_excel_orders,
    resolve_excel_filter_value,
    run_excel_report,
)
from app.schemas.reports import ReportFilters, ReportRequest, ReportType
from app.schemas.tools import ResolveFilterValueRequest, ResolveFilterValueStatus

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


def test_order_count_supports_exact_courier_location_phone_filters() -> None:
    rows = load_excel_orders(file_path=_EXCEL_PATH, sheet_name=_SHEET_NAME)
    sample = next(
        row
        for row in rows
        if row.courier is not None and row.address is not None and row.phone_number is not None
    )

    response = run_excel_report(
        ReportRequest(
            report_id=ReportType.ORDER_COUNT,
            filters=ReportFilters(
                date_from=_FULL_RANGE.date_from,
                date_to=_FULL_RANGE.date_to,
                courier=sample.courier,
                location=sample.address,
                phone_number=sample.phone_number,
            ),
        ),
        file_path=_EXCEL_PATH,
        sheet_name=_SHEET_NAME,
    )

    assert response.result.metrics[0].label == "order_count"
    assert response.result.metrics[0].value >= 1


def test_sales_total_supports_generic_source_and_courier_filters() -> None:
    rows = load_excel_orders(file_path=_EXCEL_PATH, sheet_name=_SHEET_NAME)
    sample = next(row for row in rows if row.source is not None and row.courier is not None)

    base_response = run_excel_report(
        ReportRequest(report_id=ReportType.SALES_TOTAL, filters=_FULL_RANGE),
        file_path=_EXCEL_PATH,
        sheet_name=_SHEET_NAME,
    )
    filtered_response = run_excel_report(
        ReportRequest(
            report_id=ReportType.SALES_TOTAL,
            filters=ReportFilters(
                date_from=_FULL_RANGE.date_from,
                date_to=_FULL_RANGE.date_to,
                source=sample.source,
                courier=sample.courier,
            ),
        ),
        file_path=_EXCEL_PATH,
        sheet_name=_SHEET_NAME,
    )

    assert filtered_response.result.filters.source == sample.source
    assert filtered_response.result.filters.courier == sample.courier
    assert filtered_response.result.metrics[0].value <= base_response.result.metrics[0].value


def test_sales_by_courier_supports_generic_source_filter() -> None:
    rows = load_excel_orders(file_path=_EXCEL_PATH, sheet_name=_SHEET_NAME)
    sample_source = next(row.source for row in rows if row.source is not None)

    response = run_excel_report(
        ReportRequest(
            report_id=ReportType.SALES_BY_COURIER,
            filters=ReportFilters(
                date_from=_FULL_RANGE.date_from,
                date_to=_FULL_RANGE.date_to,
                source=sample_source,
            ),
        ),
        file_path=_EXCEL_PATH,
        sheet_name=_SHEET_NAME,
    )

    assert response.result.filters.source == sample_source
    assert response.result.metrics


def test_resolve_excel_filter_value_resolves_armenian_courier_name() -> None:
    response = resolve_excel_filter_value(
        ResolveFilterValueRequest(
            report_id=ReportType.ORDER_COUNT,
            filter_key="courier",
            raw_value="Ազատ",
        ),
        file_path=_EXCEL_PATH,
        sheet_name=_SHEET_NAME,
    )

    assert response.status is ResolveFilterValueStatus.RESOLVED
    assert response.matched_value == "Azat"


def test_resolve_excel_filter_value_resolves_existing_location_exactly() -> None:
    rows = load_excel_orders(file_path=_EXCEL_PATH, sheet_name=_SHEET_NAME)
    sample = next(row for row in rows if row.address is not None)

    response = resolve_excel_filter_value(
        ResolveFilterValueRequest(
            report_id=ReportType.ORDER_COUNT,
            filter_key="location",
            raw_value=sample.address,
        ),
        file_path=_EXCEL_PATH,
        sheet_name=_SHEET_NAME,
    )

    assert response.status is ResolveFilterValueStatus.RESOLVED
    assert response.matched_value == sample.address


def test_resolve_excel_filter_value_does_not_guess_missing_location() -> None:
    response = resolve_excel_filter_value(
        ResolveFilterValueRequest(
            report_id=ReportType.ORDER_COUNT,
            filter_key="location",
            raw_value="Բաղրամյան 22",
        ),
        file_path=_EXCEL_PATH,
        sheet_name=_SHEET_NAME,
    )

    assert response.status is ResolveFilterValueStatus.UNRESOLVED
    assert response.matched_value is None


def test_resolve_excel_filter_value_resolves_phone_country_code_to_exact_digits() -> None:
    response = resolve_excel_filter_value(
        ResolveFilterValueRequest(
            report_id=ReportType.ORDER_COUNT,
            filter_key="phone_number",
            raw_value="+374 10 311111",
        ),
        file_path=_EXCEL_PATH,
        sheet_name=_SHEET_NAME,
    )

    assert response.status is ResolveFilterValueStatus.RESOLVED
    assert response.matched_value == "010311111"
