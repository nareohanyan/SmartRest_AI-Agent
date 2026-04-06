from __future__ import annotations

from datetime import datetime, time, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.schemas.reports import ReportMetric, ReportRequest, ReportResult, ReportType
from app.schemas.tools import RunReportResponse
from app.smartrest.models import Order, get_sync_session_factory

SMARTREST_BACKEND_WARNING = "smartrest_backend_live_data"
SMARTREST_BACKEND_FALLBACK_WARNING = "smartrest_backend_fallback_to_mock"


class SmartRestReportBackendUnsupportedError(ValueError):
    pass


def run_smartrest_report(
    request: ReportRequest,
    *,
    profile_id: int,
) -> RunReportResponse:
    report_id = request.report_id
    filters = request.filters
    if report_id is ReportType.SALES_BY_SOURCE:
        raise SmartRestReportBackendUnsupportedError(
            "sales_by_source is not implemented in SmartRest DB backend yet."
        )
    if filters.source is not None:
        raise SmartRestReportBackendUnsupportedError(
            f"source filter is not supported for report_id={report_id.value}"
        )

    session_factory = get_sync_session_factory()
    with session_factory() as session:
        date_from = filters.date_from
        date_to = filters.date_to
        total_expr = func.coalesce(func.sum(func.coalesce(Order.final_total, Order.total_price)), 0)
        orders_scope = (
            select(total_expr.label("sales_total"), func.count(Order.id).label("order_count"))
            .where(Order.profile_id == profile_id)
            .where(func.date(Order.order_create_date) >= date_from)
            .where(func.date(Order.order_create_date) <= date_to)
        )
        row = session.execute(orders_scope).one()
        sales_total = Decimal(str(row.sales_total or 0))
        order_count = Decimal(int(row.order_count or 0))

    if report_id is ReportType.SALES_TOTAL:
        metrics = [ReportMetric(label="sales_total", value=float(sales_total))]
    elif report_id is ReportType.ORDER_COUNT:
        metrics = [ReportMetric(label="order_count", value=float(order_count))]
    elif report_id is ReportType.AVERAGE_CHECK:
        value = Decimal("0")
        if order_count > 0:
            value = sales_total / order_count
        metrics = [ReportMetric(label="average_check", value=float(value))]
    else:
        raise SmartRestReportBackendUnsupportedError(f"Unsupported report_id: {report_id.value}")

    result = ReportResult(
        report_id=report_id,
        filters=filters,
        metrics=metrics,
        generated_at=datetime.combine(filters.date_to, time.min, tzinfo=timezone.utc),
    )
    return RunReportResponse(result=result, warnings=[SMARTREST_BACKEND_WARNING])

