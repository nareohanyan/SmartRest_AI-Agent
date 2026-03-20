"""Static report catalog for deterministic mock reporting."""

from __future__ import annotations

from app.schemas.reports import ReportDefinition, ReportFilterKey, ReportType

_COMMON_DIMENSION_FILTERS = (
    ReportFilterKey.SOURCE,
    ReportFilterKey.COURIER,
    ReportFilterKey.LOCATION,
    ReportFilterKey.PHONE_NUMBER,
)

_CATALOG: dict[ReportType, ReportDefinition] = {
    ReportType.SALES_TOTAL: ReportDefinition(
        report_id=ReportType.SALES_TOTAL,
        title="Total Sales",
        description="Total sales amount for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=_COMMON_DIMENSION_FILTERS,
    ),
    ReportType.ORDER_COUNT: ReportDefinition(
        report_id=ReportType.ORDER_COUNT,
        title="Order Count",
        description="Total number of orders for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=_COMMON_DIMENSION_FILTERS,
    ),
    ReportType.AVERAGE_CHECK: ReportDefinition(
        report_id=ReportType.AVERAGE_CHECK,
        title="Average Check",
        description="Average order value for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=_COMMON_DIMENSION_FILTERS,
    ),
    ReportType.SALES_BY_SOURCE: ReportDefinition(
        report_id=ReportType.SALES_BY_SOURCE,
        title="Sales by Source",
        description="Sales breakdown by ordering source for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=_COMMON_DIMENSION_FILTERS,
    ),
    ReportType.SALES_BY_COURIER: ReportDefinition(
        report_id=ReportType.SALES_BY_COURIER,
        title="Sales by Courier",
        description="Sales breakdown by courier for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=_COMMON_DIMENSION_FILTERS,
    ),
    ReportType.TOP_LOCATIONS: ReportDefinition(
        report_id=ReportType.TOP_LOCATIONS,
        title="Top Locations",
        description="Top delivery locations by sales for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=_COMMON_DIMENSION_FILTERS,
    ),
    ReportType.TOP_CUSTOMERS: ReportDefinition(
        report_id=ReportType.TOP_CUSTOMERS,
        title="Top Customers",
        description="Top customers by phone number and sales for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=_COMMON_DIMENSION_FILTERS,
    ),
    ReportType.REPEAT_CUSTOMER_RATE: ReportDefinition(
        report_id=ReportType.REPEAT_CUSTOMER_RATE,
        title="Repeat Customer Rate",
        description="Share of repeat customers for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=_COMMON_DIMENSION_FILTERS,
    ),
    ReportType.DELIVERY_FEE_ANALYTICS: ReportDefinition(
        report_id=ReportType.DELIVERY_FEE_ANALYTICS,
        title="Delivery Fee Analytics",
        description="Delivery fee totals and averages for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=_COMMON_DIMENSION_FILTERS,
    ),
    ReportType.PAYMENT_COLLECTION: ReportDefinition(
        report_id=ReportType.PAYMENT_COLLECTION,
        title="Payment Collection",
        description="Invoiced, paid, and collection rate metrics for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=_COMMON_DIMENSION_FILTERS,
    ),
    ReportType.OUTSTANDING_BALANCE: ReportDefinition(
        report_id=ReportType.OUTSTANDING_BALANCE,
        title="Outstanding Balance",
        description="Outstanding balance (invoiced minus paid) for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=_COMMON_DIMENSION_FILTERS,
    ),
    ReportType.DAILY_SALES_TREND: ReportDefinition(
        report_id=ReportType.DAILY_SALES_TREND,
        title="Daily Sales Trend",
        description="Day-by-day sales trend for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=_COMMON_DIMENSION_FILTERS,
    ),
    ReportType.DAILY_ORDER_TREND: ReportDefinition(
        report_id=ReportType.DAILY_ORDER_TREND,
        title="Daily Order Trend",
        description="Day-by-day order count trend for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=_COMMON_DIMENSION_FILTERS,
    ),
    ReportType.SALES_BY_WEEKDAY: ReportDefinition(
        report_id=ReportType.SALES_BY_WEEKDAY,
        title="Sales by Weekday",
        description="Sales breakdown by weekday for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=_COMMON_DIMENSION_FILTERS,
    ),
    ReportType.GROSS_PROFIT: ReportDefinition(
        report_id=ReportType.GROSS_PROFIT,
        title="Gross Profit",
        description="Gross profit and margin for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=_COMMON_DIMENSION_FILTERS,
    ),
    ReportType.LOCATION_CONCENTRATION: ReportDefinition(
        report_id=ReportType.LOCATION_CONCENTRATION,
        title="Location Concentration",
        description="Top-location concentration share for the selected date range.",
        required_filters=(ReportFilterKey.DATE_FROM, ReportFilterKey.DATE_TO),
        optional_filters=_COMMON_DIMENSION_FILTERS,
    ),
}

REPORT_CATALOG_ORDER: tuple[ReportType, ...] = (
    ReportType.SALES_TOTAL,
    ReportType.ORDER_COUNT,
    ReportType.AVERAGE_CHECK,
    ReportType.SALES_BY_SOURCE,
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
