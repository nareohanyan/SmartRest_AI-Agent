from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from app.schemas.reports import ReportFilters, ReportMetric, ReportRequest, ReportResult, ReportType
from app.schemas.tools import RunReportResponse

COLUMN_MAP: dict[str, str] = {
    "Կտրոն": "check",
    "Ամսաթիվ": "order_date",
    "Առաքիչ": "courier",
    "Մատուցող": "waiter",
    "Հաճախորդ": "customer",
    "Հասցե": "address",
    "Հեռախոսահամար": "phone_number",
    "Ինքնարժեք": "net_cost",
    "Հաշիվ": "invoice",
    "Վճարված": "paid",
    "Առաքման գումար": "delivery_fee",
    "Գումար": "total_amount",
    "Նկարագրություն": "description",
}

_REQUIRED_COLUMNS = {"order_date", "total_amount"}
EXCEL_BACKEND_WARNING = "excel_backend_file_data"


@dataclass(frozen=True)
class ExcelOrderRow:
    order_date: date
    total_amount: Decimal
    check: str | None = None
    courier: str | None = None
    waiter: str | None = None
    customer: str | None = None
    address: str | None = None
    phone_number: str | None = None
    net_cost: Decimal | None = None
    invoice: str | None = None
    paid: bool | None = None
    delivery_fee: Decimal | None = None
    description: str | None = None


def _normalize_header(value: Any) -> str:
    text = str(value or "").replace("\u00A0", " ").strip()
    return " ".join(text.split()).lower()


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_date(value: Any, *, row_number: int, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        raw = value.strip()
        fmt ="%d.%m.%y %H:%M"
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Row {row_number}: invalid {field_name} value '{value}'.")


def _parse_decimal(value: Any, *, row_number: int, field_name: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise ValueError(f"Row {row_number}: empty {field_name} value.")
        raw = raw.replace("֏", "").replace("$", "").replace("€", "")
        raw = raw.replace("\u00A0", "").replace(" ", "")
        if "," in raw and "." not in raw:
            raw = raw.replace(",", ".")
        elif "," in raw and "." in raw:
            if raw.rfind(",") > raw.rfind("."):
                raw = raw.replace(".", "").replace(",", ".")
            else:
                raw = raw.replace(",", "")
        try:
            return Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError(
                f"Row {row_number}: invalid {field_name} value '{value}'."
            ) from exc
    raise ValueError(f"Row {row_number}: invalid {field_name} value '{value}'.")


def _parse_optional_decimal(
    value: Any,
    *,
    row_number: int,
    field_name: str,
) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _parse_decimal(value, row_number=row_number, field_name=field_name)


def _parse_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "y", "paid", "վճարված", "այո"}:
        return True
    if text in {"0", "false", "no", "n", "unpaid", "չվճարված", "ոչ"}:
        return False
    return None


def load_excel_orders(
    file_path: str | Path,
    *,
    sheet_name: str | None = None,
    column_map: Mapping[str, str] = COLUMN_MAP,
) -> list[ExcelOrderRow]:
    path = Path(file_path)
    workbook = load_workbook(path, data_only=True, read_only=True)

    try:
        worksheet = workbook[sheet_name] if sheet_name else workbook.active

        header_row_idx: int | None = None
        header_values: list[Any] | None = None
        for row_idx, row in enumerate(worksheet.iter_rows(values_only=True), start=1):
            if any(cell is not None and str(cell).strip() for cell in row):
                header_row_idx = row_idx
                header_values = list(row)
                break

        if header_row_idx is None or header_values is None:
            raise ValueError("Excel file has no header row.")

        normalized_map = {
            _normalize_header(non_english): english
            for non_english, english in column_map.items()
        }

        target_to_index: dict[str, int] = {}
        for idx, header_cell in enumerate(header_values):
            key = _normalize_header(header_cell)
            target = normalized_map.get(key)
            if target:
                target_to_index[target] = idx

        missing = sorted(col for col in _REQUIRED_COLUMNS if col not in target_to_index)
        if missing:
            raise ValueError(f"Missing required mapped columns: {', '.join(missing)}")

        def get_cell(row: tuple[Any, ...], field: str) -> Any:
            index = target_to_index.get(field)
            if index is None or index >= len(row):
                return None
            return row[index]

        output: list[ExcelOrderRow] = []
        for row_number, row in enumerate(
            worksheet.iter_rows(min_row=header_row_idx + 1, values_only=True),
            start=header_row_idx + 1,
        ):
            if all(
                cell is None or (isinstance(cell, str) and not cell.strip())
                for cell in row
            ):
                continue

            output.append(
                ExcelOrderRow(
                    order_date=_parse_date(
                        get_cell(row, "order_date"),
                        row_number=row_number,
                        field_name="order_date",
                    ),
                    total_amount=_parse_decimal(
                        get_cell(row, "total_amount"),
                        row_number=row_number,
                        field_name="total_amount",
                    ),
                    check=_to_text(get_cell(row, "check")),
                    courier=_to_text(get_cell(row, "courier")),
                    waiter=_to_text(get_cell(row, "waiter")),
                    customer=_to_text(get_cell(row, "customer")),
                    address=_to_text(get_cell(row, "address")),
                    phone_number=_to_text(get_cell(row, "phone_number")),
                    net_cost=_parse_optional_decimal(
                        get_cell(row, "net_cost"),
                        row_number=row_number,
                        field_name="net_cost",
                    ),
                    invoice=_to_text(get_cell(row, "invoice")),
                    paid=_parse_optional_bool(get_cell(row, "paid")),
                    delivery_fee=_parse_optional_decimal(
                        get_cell(row, "delivery_fee"),
                        row_number=row_number,
                        field_name="delivery_fee",
                    ),
                    description=_to_text(get_cell(row, "description")),
                )
            )

        return output
    finally:
        workbook.close()


def _generated_at(filters: ReportFilters) -> datetime:
    return datetime.combine(filters.date_to, time.min, tzinfo=timezone.utc)


def _rows_in_date_range(rows: list[ExcelOrderRow], filters: ReportFilters) -> list[ExcelOrderRow]:
    return [row for row in rows if filters.date_from <= row.order_date <= filters.date_to]


def _normalize_source(source: str | None) -> str | None:
    if source is None:
        return None
    normalized = source.strip().lower()
    if not normalized:
        return None
    return normalized


def _sales_total(rows: list[ExcelOrderRow]) -> Decimal:
    return sum((row.total_amount for row in rows), start=Decimal("0"))


def _order_count(rows: list[ExcelOrderRow]) -> int:
    checks = {row.check for row in rows if row.check}
    if checks:
        return len(checks)
    return len(rows)


def _metrics_for_request(
    request: ReportRequest,
    rows: list[ExcelOrderRow],
) -> list[ReportMetric]:
    report_id = request.report_id
    filters = request.filters

    if report_id is ReportType.SALES_TOTAL:
        return [ReportMetric(label="sales_total", value=float(_sales_total(rows)))]

    if report_id is ReportType.ORDER_COUNT:
        return [ReportMetric(label="order_count", value=float(_order_count(rows)))]

    if report_id is ReportType.AVERAGE_CHECK:
        order_count = _order_count(rows)
        if order_count == 0:
            average = Decimal("0")
        else:
            average = _sales_total(rows) / Decimal(order_count)
        return [ReportMetric(label="average_check", value=float(average))]

    if report_id is ReportType.SALES_BY_SOURCE:
        source_totals: dict[str, Decimal] = {}
        for row in rows:
            source = _normalize_source(row.courier) or "unknown"
            source_totals[source] = source_totals.get(source, Decimal("0")) + row.total_amount

        requested_source = _normalize_source(filters.source)
        if requested_source is not None:
            if requested_source not in source_totals:
                raise ValueError(f"Unsupported source: {requested_source}")
            return [
                ReportMetric(label=requested_source, value=float(source_totals[requested_source])),
            ]

        return [
            ReportMetric(label=source, value=float(value))
            for source, value in sorted(source_totals.items())
        ]

    raise ValueError(f"Unsupported report_id: {report_id.value}")


def run_excel_report(
    request: ReportRequest,
    *,
    file_path: str | Path,
    sheet_name: str | None = None,
) -> RunReportResponse:
    rows = load_excel_orders(file_path=file_path, sheet_name=sheet_name)
    filtered_rows = _rows_in_date_range(rows, request.filters)
    metrics = _metrics_for_request(request, filtered_rows)
    result = ReportResult(
        report_id=request.report_id,
        filters=request.filters,
        metrics=metrics,
        generated_at=_generated_at(request.filters),
    )
    return RunReportResponse(result=result, warnings=[EXCEL_BACKEND_WARNING])
