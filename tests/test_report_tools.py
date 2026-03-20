"""Deterministic behavior tests for report tools."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest

from app.agent.report_tools import (
    get_report_definition_tool,
    list_reports_tool,
    resolve_filter_value_tool,
    resolve_scope_tool,
    run_report_tool,
)
from app.core.config import get_settings
from app.reports import MOCK_BACKEND_WARNING, REPORT_CATALOG_ORDER
from app.schemas.reports import ReportFilters, ReportRequest, ReportType
from app.schemas.tools import (
    AccessStatus,
    GetReportDefinitionRequest,
    ListReportsRequest,
    ResolveFilterValueRequest,
    ResolveFilterValueStatus,
    ResolveScopeRequest,
    RunReportRequest,
)


@pytest.fixture(autouse=True)
def _force_mock_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMARTREST_EXCEL_REPORT_FILE_PATH", "")
    monkeypatch.setenv("EXCEL_REPORT_FILE_PATH", "")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _identity_payload() -> dict[str, int | str]:
    return {
        "user_id": 123,
        "profile_id": 456,
        "profile_nick": "ChefNick",
    }


def test_resolve_scope_granted_returns_all_reports() -> None:
    request = ResolveScopeRequest.model_validate({**_identity_payload(), "metadata": {}})

    response = resolve_scope_tool(request)

    assert response.status is AccessStatus.GRANTED
    assert response.denial_reason is None
    assert response.allowed_report_ids == list(REPORT_CATALOG_ORDER)


def test_resolve_scope_denied_by_metadata_flag() -> None:
    request = ResolveScopeRequest.model_validate(
        {**_identity_payload(), "metadata": {"access": "deny"}}
    )

    response = resolve_scope_tool(request)

    assert response.status is AccessStatus.DENIED
    assert response.denial_reason == "mock_access_denied"
    assert response.allowed_report_ids == []


def test_list_reports_respects_allowed_ids_and_stable_catalog_order() -> None:
    request = ListReportsRequest.model_validate(
        {
            **_identity_payload(),
            "allowed_report_ids": ["sales_by_source", "sales_total"],
        }
    )

    response = list_reports_tool(request)

    report_ids = [definition.report_id for definition in response.reports]
    assert report_ids == [ReportType.SALES_TOTAL, ReportType.SALES_BY_SOURCE]


def test_get_report_definition_returns_static_catalog_entry() -> None:
    request = GetReportDefinitionRequest.model_validate({"report_id": "sales_by_source"})

    response = get_report_definition_tool(request)

    assert response.definition.report_id is ReportType.SALES_BY_SOURCE
    assert "ordering source" in response.definition.description.lower()


def test_run_report_sales_total_is_deterministic_for_same_input() -> None:
    request = RunReportRequest.model_validate(
        {
            **_identity_payload(),
            "request": {
                "report_id": "sales_total",
                "filters": {"date_from": "2026-03-01", "date_to": "2026-03-07"},
            },
        }
    )

    response_1 = run_report_tool(request)
    response_2 = run_report_tool(request)

    assert response_1.model_dump() == response_2.model_dump()
    assert response_1.warnings == [MOCK_BACKEND_WARNING]
    assert response_1.result.metrics[0].label == "sales_total"
    assert response_1.result.metrics[0].value == 12345.67
    assert response_1.result.generated_at == datetime.combine(
        date(2026, 3, 7),
        time.min,
        tzinfo=timezone.utc,
    )


def test_run_report_sales_by_source_without_filter_returns_all_sources() -> None:
    request = RunReportRequest(
        **_identity_payload(),
        request=ReportRequest(
            report_id=ReportType.SALES_BY_SOURCE,
            filters=ReportFilters(date_from=date(2026, 3, 1), date_to=date(2026, 3, 7)),
        ),
    )

    response = run_report_tool(request)

    metrics_map = {metric.label: metric.value for metric in response.result.metrics}
    assert metrics_map == {
        "in_store": 5200.00,
        "glovo": 4100.00,
        "wolt": 2200.00,
        "takeaway": 845.67,
    }


def test_run_report_sales_by_source_with_filter_returns_single_source() -> None:
    request = RunReportRequest(
        **_identity_payload(),
        request=ReportRequest(
            report_id=ReportType.SALES_BY_SOURCE,
            filters=ReportFilters(
                date_from=date(2026, 3, 1),
                date_to=date(2026, 3, 7),
                source="glovo",
            ),
        ),
    )

    response = run_report_tool(request)

    assert len(response.result.metrics) == 1
    assert response.result.metrics[0].label == "glovo"
    assert response.result.metrics[0].value == 4100.00


def test_run_report_unknown_source_fails() -> None:
    request = RunReportRequest(
        **_identity_payload(),
        request=ReportRequest(
            report_id=ReportType.SALES_BY_SOURCE,
            filters=ReportFilters(
                date_from=date(2026, 3, 1),
                date_to=date(2026, 3, 7),
                source="uber_eats",
            ),
        ),
    )

    with pytest.raises(ValueError, match="Unsupported source"):
        run_report_tool(request)


def test_resolve_filter_value_tool_resolves_transliterated_mock_courier() -> None:
    response = resolve_filter_value_tool(
        ResolveFilterValueRequest(
            report_id=ReportType.ORDER_COUNT,
            filter_key="courier",
            raw_value="Ազատ",
        )
    )

    assert response.status is ResolveFilterValueStatus.RESOLVED
    assert response.matched_value == "azat"


def test_resolve_filter_value_tool_returns_mock_location_candidates_for_partial_match() -> None:
    response = resolve_filter_value_tool(
        ResolveFilterValueRequest(
            report_id=ReportType.ORDER_COUNT,
            filter_key="location",
            raw_value="Kasakh Andraniki",
        )
    )

    assert response.status is ResolveFilterValueStatus.UNRESOLVED
    assert "kasakh_andraniki_29" in response.candidates


def test_resolve_filter_value_tool_resolves_phone_with_country_code() -> None:
    response = resolve_filter_value_tool(
        ResolveFilterValueRequest(
            report_id=ReportType.ORDER_COUNT,
            filter_key="phone_number",
            raw_value="+374 94 727202",
        )
    )

    assert response.status is ResolveFilterValueStatus.RESOLVED
    assert response.matched_value == "094727202"


def test_resolve_filter_value_tool_supports_generic_filters_across_reports() -> None:
    response = resolve_filter_value_tool(
        ResolveFilterValueRequest(
            report_id=ReportType.SALES_TOTAL,
            filter_key="courier",
            raw_value="Azat",
        )
    )

    assert response.status is ResolveFilterValueStatus.RESOLVED
    assert response.matched_value == "azat"


def test_run_report_sales_total_supports_source_filter() -> None:
    request = RunReportRequest(
        **_identity_payload(),
        request=ReportRequest(
            report_id=ReportType.SALES_TOTAL,
            filters=ReportFilters(
                date_from=date(2026, 3, 1),
                date_to=date(2026, 3, 7),
                source="glovo",
            ),
        ),
    )

    response = run_report_tool(request)

    assert response.result.report_id is ReportType.SALES_TOTAL
    assert response.result.filters.source == "glovo"
    assert response.result.metrics[0].value < 12345.67


def test_run_report_order_count_supports_exact_courier_location_phone_filters() -> None:
    base_request = RunReportRequest(
        **_identity_payload(),
        request=ReportRequest(
            report_id=ReportType.ORDER_COUNT,
            filters=ReportFilters(
                date_from=date(2026, 3, 1),
                date_to=date(2026, 3, 7),
            ),
        ),
    )
    filtered_request = RunReportRequest(
        **_identity_payload(),
        request=ReportRequest(
            report_id=ReportType.ORDER_COUNT,
            filters=ReportFilters(
                date_from=date(2026, 3, 1),
                date_to=date(2026, 3, 7),
                courier="Ազատ",
                location="Kasakh Andraniki 29",
                phone_number="094-727-202",
            ),
        ),
    )

    base_response = run_report_tool(base_request)
    filtered_response_1 = run_report_tool(filtered_request)
    filtered_response_2 = run_report_tool(filtered_request)

    assert filtered_response_1.model_dump() == filtered_response_2.model_dump()
    assert filtered_response_1.result.metrics[0].label == "order_count"
    assert 1.0 <= filtered_response_1.result.metrics[0].value <= 300.0
    assert filtered_response_1.result.metrics[0].value != base_response.result.metrics[0].value


def test_run_report_average_check_supports_courier_filter() -> None:
    request = RunReportRequest(
        **_identity_payload(),
        request=ReportRequest(
            report_id=ReportType.AVERAGE_CHECK,
            filters=ReportFilters(
                date_from=date(2026, 3, 1),
                date_to=date(2026, 3, 7),
                courier="Azat",
            ),
        ),
    )

    response = run_report_tool(request)

    assert response.result.report_id is ReportType.AVERAGE_CHECK
    assert response.result.filters.courier == "Azat"
    assert response.result.metrics[0].value != 35.78


@pytest.mark.parametrize(
    ("report_id", "expected_label"),
    [
        (ReportType.SALES_BY_COURIER, "azat"),
        (ReportType.TOP_LOCATIONS, "kasakh_andraniki_29"),
        (ReportType.TOP_CUSTOMERS, "094727202"),
        (ReportType.REPEAT_CUSTOMER_RATE, "repeat_customer_rate_percent"),
        (ReportType.DELIVERY_FEE_ANALYTICS, "delivery_fee_total"),
        (ReportType.PAYMENT_COLLECTION, "collection_rate_percent"),
        (ReportType.OUTSTANDING_BALANCE, "outstanding_balance"),
        (ReportType.DAILY_SALES_TREND, "2026-03-01"),
        (ReportType.DAILY_ORDER_TREND, "2026-03-01"),
        (ReportType.SALES_BY_WEEKDAY, "monday"),
        (ReportType.GROSS_PROFIT, "gross_profit"),
        (ReportType.LOCATION_CONCENTRATION, "top_10_location_share_percent"),
    ],
)
def test_run_report_extended_scopes_return_metrics(
    report_id: ReportType,
    expected_label: str,
) -> None:
    request = RunReportRequest(
        **_identity_payload(),
        request=ReportRequest(
            report_id=report_id,
            filters=ReportFilters(
                date_from=date(2026, 3, 1),
                date_to=date(2026, 3, 7),
            ),
        ),
    )

    response = run_report_tool(request)

    labels = [metric.label for metric in response.result.metrics]
    assert expected_label in labels
