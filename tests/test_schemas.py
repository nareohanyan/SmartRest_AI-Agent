"""Contract tests for typed schema boundaries."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.schemas.agent import AgentState, IntentType, RunStatus
from app.schemas.analysis import (
    BreakdownRequest,
    DimensionName,
    MetricName,
    RetrievalScope,
    TimeseriesRequest,
    TotalMetricRequest,
)
from app.schemas.reports import (
    ReportDefinition,
    ReportFilterKey,
    ReportFilters,
    ReportRequest,
    ReportResult,
    ReportType,
)
from app.schemas.tools import (
    AccessStatus,
    ExportMode,
    GetReportDefinitionRequest,
    GetReportDefinitionResponse,
    ListReportsRequest,
    ListReportsResponse,
    ResolveScopeRequest,
    ResolveScopeResponse,
    RunReportRequest,
    RunReportResponse,
    ToolOperation,
)


def _scope_response_payload() -> dict[str, object]:
    return {
        "status": "granted",
        "allowed_report_ids": ["sales_total", "order_count", "average_check"],
    }


def _identity_payload() -> dict[str, int | str]:
    return {
        "user_id": 1,
        "profile_id": 2,
        "profile_nick": "nick_1",
    }


def _filters_payload() -> dict[str, str]:
    return {"date_from": "2026-03-01", "date_to": "2026-03-07"}


def _report_definition_payload() -> dict[str, object]:
    return {
        "report_id": "sales_total",
        "title": "Total Sales",
        "description": "Total sales in selected date range.",
        "required_filters": ["date_from", "date_to"],
        "optional_filters": ["source"],
    }


def _report_result_payload() -> dict[str, object]:
    return {
        "report_id": "sales_total",
        "filters": _filters_payload(),
        "metrics": [{"label": "sales_total", "value": 12345.67}],
    }


def _agent_state_payload() -> dict[str, object]:
    return {
        "chat_id": "11111111-1111-1111-1111-111111111111",
        "run_id": "22222222-2222-2222-2222-222222222222",
        "user_question": "What were sales last week?",
        "scope_request": _identity_payload(),
        "user_scope": _scope_response_payload(),
        "intent": "get_kpi",
        "selected_report_id": "sales_total",
        "filters": _filters_payload(),
        "needs_clarification": False,
        "clarification_question": None,
        "tool_responses": {
            "resolve_scope": _scope_response_payload(),
            "run_report": {"result": _report_result_payload(), "warnings": []},
        },
        "warnings": [],
        "final_answer": "Sales were 12,345.67 in the selected period.",
        "status": "completed",
    }


def test_agent_state_valid_payload() -> None:
    state = AgentState.model_validate(_agent_state_payload())

    assert state.intent is IntentType.GET_KPI
    assert state.status is RunStatus.COMPLETED
    assert state.selected_report_id is ReportType.SALES_TOTAL
    assert state.filters is not None
    assert state.filters.date_from == date(2026, 3, 1)


def test_agent_state_missing_required_field_fails() -> None:
    payload = _agent_state_payload()
    payload.pop("run_id")

    with pytest.raises(ValidationError) as exc_info:
        AgentState.model_validate(payload)

    assert any(
        error["loc"] == ("run_id",) and error["type"] == "missing"
        for error in exc_info.value.errors()
    )


def test_agent_state_wrong_type_fails() -> None:
    payload = _agent_state_payload()
    payload["warnings"] = "none"

    with pytest.raises(ValidationError) as exc_info:
        AgentState.model_validate(payload)

    assert any(error["loc"] == ("warnings",) for error in exc_info.value.errors())


def test_agent_state_invalid_enum_value_fails() -> None:
    payload = _agent_state_payload()
    payload["intent"] = "unknown_intent"

    with pytest.raises(ValidationError) as exc_info:
        AgentState.model_validate(payload)

    assert any(
        error["loc"] == ("intent",) and error["type"] == "enum"
        for error in exc_info.value.errors()
    )


def test_agent_state_extra_field_fails() -> None:
    payload = _agent_state_payload()
    payload["unexpected_field"] = "future-value"

    with pytest.raises(ValidationError) as exc_info:
        AgentState.model_validate(payload)

    assert any(
        error["loc"] == ("unexpected_field",) and error["type"] == "extra_forbidden"
        for error in exc_info.value.errors()
    )


def test_agent_state_onboarding_disallows_clarification_flags() -> None:
    payload = _agent_state_payload()
    payload["status"] = "onboarding"
    payload["needs_clarification"] = True
    payload["clarification_question"] = "Please provide a date range."

    with pytest.raises(ValidationError) as exc_info:
        AgentState.model_validate(payload)

    assert "status=onboarding requires needs_clarification=false" in str(exc_info.value)


def test_agent_state_onboarding_disallows_clarification_question() -> None:
    payload = _agent_state_payload()
    payload["status"] = "onboarding"
    payload["needs_clarification"] = False
    payload["clarification_question"] = "Please provide a date range."

    with pytest.raises(ValidationError) as exc_info:
        AgentState.model_validate(payload)

    assert "status=onboarding requires clarification_question=null" in str(exc_info.value)


def test_report_contracts_valid_payloads() -> None:
    report_filters = ReportFilters.model_validate(_filters_payload())
    report_request = ReportRequest.model_validate(
        {"report_id": "sales_total", "filters": _filters_payload()}
    )
    report_definition = ReportDefinition.model_validate(_report_definition_payload())
    report_result = ReportResult.model_validate(_report_result_payload())

    assert report_filters.date_to == date(2026, 3, 7)
    assert report_request.report_id is ReportType.SALES_TOTAL
    assert report_definition.required_filters == (
        ReportFilterKey.DATE_FROM,
        ReportFilterKey.DATE_TO,
    )
    assert report_result.metrics[0].label == "sales_total"


def test_report_contract_invalid_report_id_fails() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ReportRequest.model_validate(
            {"report_id": "gross_profit", "filters": _filters_payload()}
        )

    assert any(
        error["loc"] == ("report_id",) and error["type"] == "enum"
        for error in exc_info.value.errors()
    )


def test_report_contract_invalid_or_missing_dates_fail() -> None:
    with pytest.raises(ValidationError) as missing_date_exc:
        ReportFilters.model_validate({"date_from": "2026-03-01"})

    assert any(
        error["loc"] == ("date_to",) and error["type"] == "missing"
        for error in missing_date_exc.value.errors()
    )

    with pytest.raises(ValidationError) as invalid_range_exc:
        ReportFilters.model_validate({"date_from": "2026-03-08", "date_to": "2026-03-01"})

    assert "date_from must be on or before date_to" in str(invalid_range_exc.value)


def test_resolve_scope_contracts_valid_and_invalid() -> None:
    scope_request = ResolveScopeRequest.model_validate(_identity_payload())
    scope_response = ResolveScopeResponse.model_validate(_scope_response_payload())

    assert scope_request.user_id == 1
    assert scope_response.status is AccessStatus.GRANTED
    assert scope_response.allowed_branch_ids == ["*"]
    assert scope_response.allowed_export_modes is not None
    assert scope_response.allowed_metric_ids == [metric.value for metric in MetricName]
    assert scope_response.allowed_dimension_ids == [
        dimension.value for dimension in DimensionName
    ]
    assert scope_response.allowed_metrics == list(MetricName)
    assert scope_response.allowed_dimensions == list(DimensionName)
    assert scope_response.allowed_tool_operations == list(ToolOperation)

    with pytest.raises(ValidationError) as missing_field_exc:
        ResolveScopeRequest.model_validate({"user_id": 1, "profile_nick": "nick_1"})

    assert any(
        error["loc"] == ("profile_id",) and error["type"] == "missing"
        for error in missing_field_exc.value.errors()
    )

    with pytest.raises(ValidationError) as denied_reason_exc:
        ResolveScopeResponse.model_validate(
            {
                "status": "denied",
                "allowed_report_ids": [],
            }
        )

    assert "denial_reason is required when status is denied" in str(denied_reason_exc.value)


def test_resolve_scope_accepts_explicit_granular_permissions() -> None:
    scope_response = ResolveScopeResponse.model_validate(
        {
            "status": "granted",
            "allowed_report_ids": ["sales_total"],
            "allowed_branch_ids": ["branch_1"],
            "allowed_export_modes": ["csv"],
            "allowed_metrics": ["sales_total"],
            "allowed_dimensions": ["source"],
            "allowed_tool_operations": ["fetch_breakdown", "top_k"],
        }
    )

    assert scope_response.allowed_branch_ids == ["branch_1"]
    assert scope_response.allowed_export_modes == [ExportMode.CSV]
    assert scope_response.allowed_metrics == [MetricName.SALES_TOTAL]
    assert scope_response.allowed_dimensions == [DimensionName.SOURCE]
    assert scope_response.allowed_metric_ids == [MetricName.SALES_TOTAL.value]
    assert scope_response.allowed_dimension_ids == [DimensionName.SOURCE.value]
    assert scope_response.allowed_tool_operations == [
        ToolOperation.FETCH_BREAKDOWN,
        ToolOperation.TOP_K,
    ]


def test_resolve_scope_accepts_id_permissions_outside_legacy_enums() -> None:
    scope_response = ResolveScopeResponse.model_validate(
        {
            "status": "granted",
            "allowed_report_ids": ["sales_total"],
            "allowed_branch_ids": ["branch_1", "branch_2"],
            "allowed_export_modes": ["xlsx"],
            "allowed_metric_ids": ["sales_total", "completed_order_count"],
            "allowed_dimension_ids": ["source", "branch"],
            "allowed_tool_operations": ["fetch_breakdown"],
        }
    )

    assert scope_response.allowed_branch_ids == ["branch_1", "branch_2"]
    assert scope_response.allowed_export_modes == [ExportMode.XLSX]
    assert scope_response.allowed_metric_ids == ["sales_total", "completed_order_count"]
    assert scope_response.allowed_dimension_ids == ["source", "branch"]
    assert scope_response.allowed_metrics == [
        MetricName.SALES_TOTAL,
        MetricName.COMPLETED_ORDER_COUNT,
    ]
    assert scope_response.allowed_dimensions == [DimensionName.SOURCE, DimensionName.BRANCH]


def test_resolve_scope_request_accepts_requested_branch_and_export() -> None:
    scope_request = ResolveScopeRequest.model_validate(
        {
            **_identity_payload(),
            "requested_branch_ids": ["branch_1"],
            "requested_export_mode": "csv",
        }
    )

    assert scope_request.requested_branch_ids == ["branch_1"]
    assert scope_request.requested_export_mode is ExportMode.CSV


def test_analysis_retrieval_requests_accept_live_scope() -> None:
    scope = RetrievalScope.model_validate(
        {
            "profile_id": 42,
            "branch_ids": [7, 8],
            "source": "glovo",
        }
    )

    total_request = TotalMetricRequest.model_validate(
        {
            "metric": "sales_total",
            "date_from": "2026-03-01",
            "date_to": "2026-03-07",
            "scope": scope.model_dump(),
        }
    )
    breakdown_request = BreakdownRequest.model_validate(
        {
            "metric": "sales_total",
            "dimension": "branch",
            "date_from": "2026-03-01",
            "date_to": "2026-03-07",
            "scope": scope.model_dump(),
        }
    )
    timeseries_request = TimeseriesRequest.model_validate(
        {
            "metric": "sales_total",
            "date_from": "2026-03-01",
            "date_to": "2026-03-07",
            "dimension": "day",
            "scope": scope.model_dump(),
        }
    )

    assert total_request.scope == scope
    assert breakdown_request.scope == scope
    assert timeseries_request.scope == scope


def test_list_reports_contracts_valid_and_invalid() -> None:
    list_request = ListReportsRequest.model_validate(
        {**_identity_payload(), "allowed_report_ids": ["sales_total"]}
    )
    list_response = ListReportsResponse.model_validate({"reports": [_report_definition_payload()]})

    assert list_request.allowed_report_ids == [ReportType.SALES_TOTAL]
    assert list_response.reports[0].report_id is ReportType.SALES_TOTAL

    with pytest.raises(ValidationError) as missing_field_exc:
        ListReportsRequest.model_validate(_identity_payload())

    assert any(
        error["loc"] == ("allowed_report_ids",) and error["type"] == "missing"
        for error in missing_field_exc.value.errors()
    )


def test_get_report_definition_contracts_valid_and_invalid() -> None:
    definition_request = GetReportDefinitionRequest.model_validate({"report_id": "sales_total"})
    definition_response = GetReportDefinitionResponse.model_validate(
        {"definition": _report_definition_payload()}
    )

    assert definition_request.report_id is ReportType.SALES_TOTAL
    assert definition_response.definition.report_id is ReportType.SALES_TOTAL

    with pytest.raises(ValidationError) as invalid_id_exc:
        GetReportDefinitionRequest.model_validate({"report_id": "menu_mix"})

    assert any(
        error["loc"] == ("report_id",) and error["type"] == "enum"
        for error in invalid_id_exc.value.errors()
    )


def test_run_report_contracts_valid_and_invalid() -> None:
    run_request = RunReportRequest.model_validate(
        {
            **_identity_payload(),
            "request": {"report_id": "sales_total", "filters": _filters_payload()},
        }
    )
    run_response = RunReportResponse.model_validate(
        {"result": _report_result_payload(), "warnings": ["mock-result"]}
    )

    assert run_request.request.report_id is ReportType.SALES_TOTAL
    assert run_response.result.report_id is ReportType.SALES_TOTAL

    with pytest.raises(ValidationError) as missing_request_exc:
        RunReportRequest.model_validate(_identity_payload())

    assert any(
        error["loc"] == ("request",) and error["type"] == "missing"
        for error in missing_request_exc.value.errors()
    )

    with pytest.raises(ValidationError) as empty_metrics_exc:
        RunReportResponse.model_validate(
            {
                "result": {
                    "report_id": "sales_total",
                    "filters": _filters_payload(),
                    "metrics": [],
                }
            }
        )

    assert any(error["loc"] == ("result", "metrics") for error in empty_metrics_exc.value.errors())


def test_schema_evolution_rejects_unknown_nested_fields() -> None:
    with pytest.raises(ValidationError) as exc_info:
        RunReportRequest.model_validate(
            {
                **_identity_payload(),
                "request": {
                    "report_id": "sales_total",
                    "filters": {
                        "date_from": "2026-03-01",
                        "date_to": "2026-03-07",
                        "timezone": "UTC",
                    },
                },
            }
        )

    assert any(
        error["loc"] == ("request", "filters", "timezone")
        and error["type"] == "extra_forbidden"
        for error in exc_info.value.errors()
    )
