"""Static report catalog for deterministic mock reporting."""

from __future__ import annotations

from app.schemas.reports import ReportDefinition, ReportFilterKey, ReportType

_CATALOG: dict[ReportType, ReportDefinition] = {
    ReportType.SALES_TOTAL: ReportDefinition(
        report_id=ReportType.SALES_TOTAL,
        title="Total Sales",
        description="Total sales amount for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=(),
    ),
    ReportType.ORDER_COUNT: ReportDefinition(
        report_id=ReportType.ORDER_COUNT,
        title="Order Count",
        description="Total number of orders for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=(),
    ),
    ReportType.AVERAGE_CHECK: ReportDefinition(
        report_id=ReportType.AVERAGE_CHECK,
        title="Average Check",
        description="Average order value for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=(),
    ),
    ReportType.SALES_BY_SOURCE: ReportDefinition(
        report_id=ReportType.SALES_BY_SOURCE,
        title="Sales by Source",
        description="Sales breakdown by ordering source for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=(ReportFilterKey.SOURCE,),
    ),
}

REPORT_CATALOG_ORDER: tuple[ReportType, ...] = (
    ReportType.SALES_TOTAL,
    ReportType.ORDER_COUNT,
    ReportType.AVERAGE_CHECK,
    ReportType.SALES_BY_SOURCE,
)


def list_report_definitions(allowed_report_ids: list[ReportType]) -> list[ReportDefinition]:
    """Return report definitions in stable catalog order for allowed report IDs."""
    allowed = set(allowed_report_ids)
    return [
        _CATALOG[report_id].model_copy(deep=True)
        for report_id in REPORT_CATALOG_ORDER
        if report_id in allowed
    ]


def get_report_definition(report_id: ReportType) -> ReportDefinition:
    """Return one report definition by report ID."""
    try:
        return _CATALOG[report_id].model_copy(deep=True)
    except KeyError as exc:
        raise ValueError(f"Unknown report_id: {report_id}") from exc
