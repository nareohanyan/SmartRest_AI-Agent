from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.services.smartrest_query_support import (
    apply_order_filters,
    normalize_source_filter,
    sales_total_expression,
    source_bucket_expression,
)
from app.schemas.reports import ReportMetric, ReportRequest, ReportResult, ReportType
from app.schemas.tools import RunReportResponse
from app.smartrest.models import Order, get_sync_session_factory

SMARTREST_BACKEND_WARNING = "smartrest_backend_live_data"


class SmartRestReportBackendUnsupportedError(ValueError):
    pass


def run_smartrest_report(
    request: ReportRequest,
    *,
    profile_id: int,
) -> RunReportResponse:
    report_id = request.report_id
    filters = request.filters
    if filters.source is not None and report_id is not ReportType.SALES_BY_SOURCE:
        raise ValueError(f"Source filter is not supported for report_id={report_id.value}")

    session_factory = get_sync_session_factory()
    with session_factory() as session:
        date_from = filters.date_from
        date_to = filters.date_to

        if report_id is ReportType.SALES_BY_SOURCE:
            metrics = _run_sales_by_source_report(
                session=session,
                profile_id=profile_id,
                date_from=date_from,
                date_to=date_to,
                source=filters.source,
            )
        else:
            metrics = _run_totals_report(
                session=session,
                profile_id=profile_id,
                report_id=report_id,
                date_from=date_from,
                date_to=date_to,
            )

    result = ReportResult(
        report_id=report_id,
        filters=filters,
        metrics=metrics,
        generated_at=datetime.combine(filters.date_to, time.min, tzinfo=timezone.utc),
    )
    return RunReportResponse(result=result, warnings=[SMARTREST_BACKEND_WARNING])


def _run_totals_report(
    *,
    session: Session,
    profile_id: int,
    report_id: ReportType,
    date_from: date,
    date_to: date,
) -> list[ReportMetric]:
    statement = select(
        sales_total_expression().label("sales_total"),
        func.count(Order.id).label("order_count"),
    )
    statement = apply_order_filters(
        statement,
        profile_id=profile_id,
        date_from=date_from,
        date_to=date_to,
    )
    row = session.execute(statement).one()
    sales_total = Decimal(str(row.sales_total or 0))
    order_count = Decimal(int(row.order_count or 0))

    if report_id is ReportType.SALES_TOTAL:
        return [ReportMetric(label="sales_total", value=float(sales_total))]
    if report_id is ReportType.ORDER_COUNT:
        return [ReportMetric(label="order_count", value=float(order_count))]
    if report_id is ReportType.AVERAGE_CHECK:
        value = Decimal("0")
        if order_count > 0:
            value = sales_total / order_count
        return [ReportMetric(label="average_check", value=float(value))]
    raise SmartRestReportBackendUnsupportedError(f"Unsupported report_id: {report_id.value}")


def _run_sales_by_source_report(
    *,
    session: Session,
    profile_id: int,
    date_from: date,
    date_to: date,
    source: str | None,
) -> list[ReportMetric]:
    normalized_source = normalize_source_filter(source)
    bucket_expression = source_bucket_expression()
    statement = select(
        bucket_expression.label("source"),
        sales_total_expression().label("sales_total"),
    ).group_by(bucket_expression).order_by(bucket_expression)
    statement = apply_order_filters(
        statement,
        profile_id=profile_id,
        date_from=date_from,
        date_to=date_to,
        source=normalized_source,
    )
    rows = session.execute(statement).all()

    values_by_source = {
        str(row.source): Decimal(str(row.sales_total or 0))
        for row in rows
    }
    if normalized_source is not None:
        return [
            ReportMetric(
                label=normalized_source,
                value=float(values_by_source.get(normalized_source, Decimal("0"))),
            )
        ]

    return [
        ReportMetric(label="in_store", value=float(values_by_source.get("in_store", Decimal("0")))),
        ReportMetric(label="takeaway", value=float(values_by_source.get("takeaway", Decimal("0")))),
    ]
