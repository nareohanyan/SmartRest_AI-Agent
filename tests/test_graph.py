"""End-to-end tests for the minimal Task 9 LangGraph workflow."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

import app.agent.graph as graph_module
from app.agent.graph import build_agent_graph
from app.agent.llm.exceptions import LLMClientError
from app.core.config import get_settings
from app.persistence.runtime_persistence import FinishRunPersistenceResult
from app.schemas.agent import AgentState, LLMErrorCategory, RunStatus
from app.schemas.reports import ReportType
from app.schemas.tools import (
    AccessStatus,
    ResolveFilterValueResponse,
    ResolveFilterValueStatus,
    ResolveScopeResponse,
)


class _FakeLLMClient:
    def __init__(self, *, output_text: str | None = None, exc: Exception | None = None) -> None:
        self._output_text = output_text
        self._exc = exc
        self.calls: list[dict[str, Any]] = []

    def generate_text(
        self,
        *,
        messages: Sequence[dict[str, str]],
        model: str | None = None,
    ) -> str:
        self.calls.append({"messages": list(messages), "model": model})
        if self._exc is not None:
            raise self._exc
        if self._output_text is None:
            raise AssertionError("No fake LLM output configured.")
        return self._output_text


def _missing_openai_key() -> Any:
    raise ValueError("OPENAI_API_KEY is not configured.")


@pytest.fixture(autouse=True)
def _default_to_missing_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph_module, "get_llm_client", _missing_openai_key)


@pytest.fixture(autouse=True)
def _force_mock_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMARTREST_EXCEL_REPORT_FILE_PATH", "")
    monkeypatch.setenv("EXCEL_REPORT_FILE_PATH", "")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _scope_request_payload(*, deny: bool = False) -> dict[str, object]:
    metadata: dict[str, str] = {"access": "deny"} if deny else {}
    return {
        "user_id": 101,
        "profile_id": 201,
        "profile_nick": "Nick",
        "metadata": metadata,
    }


def _initial_state(question: str, *, deny_scope: bool = False) -> dict[str, object]:
    return {
        "thread_id": "11111111-1111-1111-1111-111111111111",
        "run_id": "22222222-2222-2222-2222-222222222222",
        "user_question": question,
        "scope_request": _scope_request_payload(deny=deny_scope),
        "needs_clarification": False,
        "status": "running",
    }


def _node_order(graph: Any, payload: dict[str, object]) -> list[str]:
    order: list[str] = []
    for chunk in graph.stream(payload, stream_mode="updates"):
        order.extend(chunk.keys())
    return order


def test_supported_request_executes_full_run_path() -> None:
    graph = build_agent_graph()
    payload = _initial_state("What were total sales 2026-03-01 to 2026-03-07?")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "openai_interpret",
        "authorize_report",
        "run_report",
        "calc_metrics",
        "reason_over_results",
        "compose_output",
        "persist_run",
    ]
    assert final_state.status is RunStatus.COMPLETED
    assert final_state.selected_report_id is ReportType.SALES_TOTAL
    assert final_state.tool_responses.run_report is not None
    sales_total_value = Decimal(
        str(final_state.tool_responses.run_report.result.metrics[0].value)
    )
    assert final_state.base_metrics["sales_total"] == sales_total_value
    assert len(final_state.derived_metrics) == 1
    assert final_state.derived_metrics[0].key == "sales_total_per_day"
    assert final_state.final_answer is not None
    assert "total sales" in final_state.final_answer.lower()
    assert "per day" not in final_state.final_answer.lower()
    assert "=" not in final_state.final_answer


def test_small_talk_routes_without_report_execution() -> None:
    graph = build_agent_graph()
    payload = _initial_state("Hello there")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "openai_interpret",
        "authorize_report",
        "small_talk",
        "persist_run",
    ]
    assert final_state.status is RunStatus.COMPLETED
    assert final_state.selected_report_id is None
    assert final_state.tool_responses.run_report is None
    assert final_state.final_answer is not None
    assert "analytics" in final_state.final_answer.lower()


def test_small_talk_uses_llm_generation_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeLLMClient(output_text="Hello. Ask me about sales or orders.")
    monkeypatch.setattr(graph_module, "get_llm_client", lambda: fake_client)
    graph = build_agent_graph()

    final_state = AgentState.model_validate(graph.invoke(_initial_state("Hello there")))

    assert final_state.status is RunStatus.COMPLETED
    assert final_state.tool_responses.run_report is None
    assert final_state.final_answer == "Hello. Ask me about sales or orders."
    assert len(fake_client.calls) == 1


def test_greeting_with_analytics_request_prioritizes_report_path() -> None:
    graph = build_agent_graph()
    payload = _initial_state("Hi, what were total sales 2026-03-01 to 2026-03-07?")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "openai_interpret",
        "authorize_report",
        "run_report",
        "calc_metrics",
        "reason_over_results",
        "compose_output",
        "persist_run",
    ]
    assert final_state.status is RunStatus.COMPLETED
    assert final_state.selected_report_id is ReportType.SALES_TOTAL


def test_multi_intent_request_returns_structured_multi_block_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMARTREST_EXCEL_REPORT_FILE_PATH", "")
    monkeypatch.setenv("EXCEL_REPORT_FILE_PATH", "")
    get_settings.cache_clear()
    try:
        graph = build_agent_graph()
        payload = _initial_state("Show top locations and total sales 2026-03-01 to 2026-03-07.")

        final_state = AgentState.model_validate(graph.invoke(payload))
        order = _node_order(graph, payload)

        assert order == [
            "resolve_scope",
            "openai_interpret",
            "authorize_report",
            "run_report",
            "calc_metrics",
            "reason_over_results",
            "compose_output",
            "persist_run",
        ]
        assert final_state.status is RunStatus.COMPLETED
        assert len(final_state.additional_run_reports) == 1
        assert final_state.final_answer is not None
        assert "top locations" in final_state.final_answer.lower()
        assert "total sales" in final_state.final_answer.lower()
        assert "\n\n" in final_state.final_answer
        assert "1. " not in final_state.final_answer
        assert "=" not in final_state.final_answer
    finally:
        get_settings.cache_clear()


def test_multi_intent_request_preserves_sentence_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMARTREST_EXCEL_REPORT_FILE_PATH", "")
    monkeypatch.setenv("EXCEL_REPORT_FILE_PATH", "")
    get_settings.cache_clear()
    try:
        graph = build_agent_graph()
        payload = _initial_state("Show total sales and top locations 2026-03-01 to 2026-03-07.")

        final_state = AgentState.model_validate(graph.invoke(payload))

        assert final_state.status is RunStatus.COMPLETED
        assert final_state.selected_report_id is ReportType.SALES_TOTAL
        assert len(final_state.additional_run_reports) == 1
        assert final_state.additional_run_reports[0].result.report_id is ReportType.TOP_LOCATIONS
    finally:
        get_settings.cache_clear()


def test_top_n_slot_limits_display_for_ranked_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMARTREST_EXCEL_REPORT_FILE_PATH", "")
    monkeypatch.setenv("EXCEL_REPORT_FILE_PATH", "")
    get_settings.cache_clear()
    try:
        graph = build_agent_graph()
        payload = _initial_state("Show top 2 locations 2026-03-01 to 2026-03-07.")

        final_state = AgentState.model_validate(graph.invoke(payload))

        assert final_state.status is RunStatus.COMPLETED
        assert final_state.selected_report_id is ReportType.TOP_LOCATIONS
        assert final_state.requested_top_n == 2
        assert final_state.final_answer is not None
        assert "=" not in final_state.final_answer
        assert "kasakh andraniki 29" in final_state.final_answer.lower()
        assert "bagratunyats 18" in final_state.final_answer.lower()
        assert "droi 6 48" not in final_state.final_answer.lower()
    finally:
        get_settings.cache_clear()


def test_average_check_without_formula_policy_still_completes() -> None:
    graph = build_agent_graph()
    payload = _initial_state("What was average check 2026-03-01 to 2026-03-07?")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "openai_interpret",
        "authorize_report",
        "run_report",
        "calc_metrics",
        "reason_over_results",
        "compose_output",
        "persist_run",
    ]
    assert final_state.status is RunStatus.COMPLETED
    assert final_state.selected_report_id is ReportType.AVERAGE_CHECK
    assert final_state.derived_metrics == []
    assert "calc_no_formulas_selected" in final_state.warnings


def test_completed_answer_is_localized_for_armenian_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _armenian_interpretation(_question: str) -> dict[str, object]:
        return {
            "intent": "get_kpi",
            "report_id": "sales_total",
            "filters": {"date_from": "2026-03-01", "date_to": "2026-03-07"},
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.95,
            "reasoning_notes": "Armenian localization path.",
        }

    monkeypatch.setattr(graph_module, "_generate_interpretation_payload", _armenian_interpretation)
    graph = build_agent_graph()
    payload = _initial_state("Ընդհանուր վաճառքը 2026-03-01 to 2026-03-07?")

    final_state = AgentState.model_validate(graph.invoke(payload))

    assert final_state.status is RunStatus.COMPLETED
    assert final_state.final_answer is not None
    assert "ընդհանուր վաճառք" in final_state.final_answer.lower()
    assert "=" not in final_state.final_answer


def test_rejected_answer_is_localized_for_russian_question() -> None:
    graph = build_agent_graph()
    payload = _initial_state("Покажи тренд зарплат 2026-03-01 to 2026-03-07.")

    final_state = AgentState.model_validate(graph.invoke(payload))

    assert final_state.status is RunStatus.REJECTED
    assert final_state.final_answer is not None
    assert final_state.final_answer.startswith("Неподдерживаемый запрос")


def test_missing_date_defaults_to_all_time_without_clarification() -> None:
    graph = build_agent_graph()
    payload = _initial_state("What were total sales?")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "openai_interpret",
        "authorize_report",
        "run_report",
        "calc_metrics",
        "reason_over_results",
        "compose_output",
        "persist_run",
    ]
    assert final_state.status is RunStatus.COMPLETED
    assert final_state.needs_clarification is False
    assert final_state.tool_responses.run_report is not None
    assert final_state.filters is not None
    assert final_state.filters.date_from == date(2026, 3, 1)
    assert final_state.filters.date_to == date(2026, 3, 7)


def test_delivery_count_with_armenian_location_without_exact_match_clarifies() -> None:
    graph = build_agent_graph()
    payload = _initial_state("Բաղրամյան 22֊ում քանի հատ առաքում ա եղել 2024-12-01 to 2024-12-31")

    final_state = AgentState.model_validate(graph.invoke(payload))

    assert final_state.status is RunStatus.CLARIFY
    assert final_state.selected_report_id is ReportType.ORDER_COUNT
    assert final_state.final_answer is not None
    assert "բաղրամյան 22" in final_state.final_answer.lower()
    assert "saryan 22" not in final_state.final_answer.lower()


def test_delivery_count_with_armenian_courier_resolves_to_canonical_value() -> None:
    graph = build_agent_graph()
    payload = _initial_state("Ազատը քանի հատ առաքում ա արել 2024-12-01 to 2024-12-31")

    final_state = AgentState.model_validate(graph.invoke(payload))

    assert final_state.status is RunStatus.COMPLETED
    assert final_state.selected_report_id is ReportType.ORDER_COUNT
    assert final_state.filters is not None
    assert final_state.filters.courier == "azat"
    assert final_state.filters.location is None
    assert final_state.filters.phone_number is None


def test_translit_delivery_count_with_trailing_courier_resolves() -> None:
    graph = build_agent_graph()
    payload = _initial_state("es amsva mej qani hat araquma arel Yandexy")

    final_state = AgentState.model_validate(graph.invoke(payload))

    assert final_state.status is RunStatus.COMPLETED
    assert final_state.selected_report_id is ReportType.ORDER_COUNT
    assert final_state.filters is not None
    assert final_state.filters.date_from == date(2026, 3, 1)
    assert final_state.filters.date_to == date(2026, 3, 24)
    assert final_state.filters.courier == "yandex"
    assert final_state.final_answer is not None
    assert "yandex" in final_state.final_answer.lower()


def test_armenian_delivery_count_phrase_maps_to_order_count_and_courier_slot() -> None:
    query = "Արթուրի ընդհանուր առաքումներ քանակը որքան է կազմում"

    assert graph_module._detect_report_id(query) is ReportType.ORDER_COUNT
    slots = graph_module._extract_query_slots(query)
    assert slots.metric == "order_count"
    assert slots.courier == "արթուր"


def test_order_count_query_resolves_exact_phone_number_filter() -> None:
    graph = build_agent_graph()
    payload = _initial_state("094727202 համարից քանի պատվեր է եղել 2024-12-01 to 2024-12-31")

    final_state = AgentState.model_validate(graph.invoke(payload))

    assert final_state.status is RunStatus.COMPLETED
    assert final_state.selected_report_id is ReportType.ORDER_COUNT
    assert final_state.filters is not None
    assert final_state.filters.phone_number == "094727202"


def test_order_count_filter_resolution_uses_llm_candidate_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_resolve_filter(_request: Any) -> ResolveFilterValueResponse:
        return ResolveFilterValueResponse(
            status=ResolveFilterValueStatus.UNRESOLVED,
            matched_value=None,
            candidates=["Azat", "Edgar"],
        )

    monkeypatch.setattr(graph_module, "resolve_filter_value_tool", _fake_resolve_filter)
    monkeypatch.setattr(
        graph_module,
        "get_llm_client",
        lambda: _FakeLLMClient(
            output_text=json.dumps(
                {
                    "matched_value": "Azat",
                    "confidence": 0.92,
                    "reasoning_notes": "Resolved against provided candidates.",
                }
            )
        ),
    )
    graph = build_agent_graph()
    payload = _initial_state("Ազատը քանի հատ առաքում ա արել 2024-12-01 to 2024-12-31")

    final_state = AgentState.model_validate(graph.invoke(payload))

    assert final_state.status is RunStatus.COMPLETED
    assert final_state.filters is not None
    assert final_state.filters.courier == "Azat"
    assert "filter_resolution_llm_used:courier" in final_state.warnings


def test_sales_total_query_supports_generic_source_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMARTREST_EXCEL_REPORT_FILE_PATH", "")
    monkeypatch.setenv("EXCEL_REPORT_FILE_PATH", "")
    get_settings.cache_clear()
    try:
        graph = build_agent_graph()
        payload = _initial_state("Show total sales source glovo 2026-03-01 to 2026-03-07.")

        final_state = AgentState.model_validate(graph.invoke(payload))

        assert final_state.status is RunStatus.COMPLETED
        assert final_state.selected_report_id is ReportType.SALES_TOTAL
        assert final_state.filters is not None
        assert final_state.filters.source == "glovo"
        assert final_state.final_answer is not None
        assert "glovo" in final_state.final_answer.lower()
        assert "filter" not in final_state.final_answer.lower()
        assert "=" not in final_state.final_answer
    finally:
        get_settings.cache_clear()


def test_average_check_query_supports_generic_courier_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMARTREST_EXCEL_REPORT_FILE_PATH", "")
    monkeypatch.setenv("EXCEL_REPORT_FILE_PATH", "")
    get_settings.cache_clear()
    try:
        graph = build_agent_graph()
        payload = _initial_state("Show average check courier Azat 2026-03-01 to 2026-03-07.")

        final_state = AgentState.model_validate(graph.invoke(payload))

        assert final_state.status is RunStatus.COMPLETED
        assert final_state.selected_report_id is ReportType.AVERAGE_CHECK
        assert final_state.filters is not None
        assert final_state.filters.courier == "azat"
        assert final_state.final_answer is not None
        assert "azat" in final_state.final_answer.lower()
        assert "filter" not in final_state.final_answer.lower()
    finally:
        get_settings.cache_clear()


def test_extract_filters_supports_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph_module, "_today", lambda: date(2026, 3, 19))

    filters = graph_module._extract_filters("What were total sales today?")

    assert filters is not None
    assert filters.date_from == date(2026, 3, 19)
    assert filters.date_to == date(2026, 3, 19)


def test_extract_filters_supports_previous_week(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph_module, "_today", lambda: date(2026, 3, 19))

    filters = graph_module._extract_filters("Show order count previous week.")

    assert filters is not None
    assert filters.date_from == date(2026, 3, 9)
    assert filters.date_to == date(2026, 3, 15)


def test_extract_filters_supports_last_three_years(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph_module, "_today", lambda: date(2026, 3, 19))

    filters = graph_module._extract_filters("Show gross profit for last 3 years.")

    assert filters is not None
    assert filters.date_from == date(2024, 1, 1)
    assert filters.date_to == date(2026, 3, 19)


def test_extract_filters_supports_russian_relative_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(graph_module, "_today", lambda: date(2026, 3, 19))

    filters = graph_module._extract_filters("Покажи продажи за прошлый месяц.")

    assert filters is not None
    assert filters.date_from == date(2026, 2, 1)
    assert filters.date_to == date(2026, 2, 28)


def test_extract_filters_supports_armenian_relative_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(graph_module, "_today", lambda: date(2026, 3, 19))

    filters = graph_module._extract_filters("Ցույց տուր վաճառքը այս տարի։")

    assert filters is not None
    assert filters.date_from == date(2026, 1, 1)
    assert filters.date_to == date(2026, 3, 19)


def test_extract_filters_supports_armenian_month_suffix_relative_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(graph_module, "_today", lambda: date(2026, 3, 19))

    filters = graph_module._extract_filters("Կարո՞ղ ես ցույց տալ վերջին 3 ամսվա ընդհանուր վաճառքը")

    assert filters is not None
    assert filters.date_from == date(2026, 1, 1)
    assert filters.date_to == date(2026, 3, 19)


@pytest.mark.parametrize(
    "question",
    [
        "Show total sales es amis",
        "Show total sales ays amsva",
    ],
)
def test_extract_filters_supports_armenian_translit_month_variants(
    monkeypatch: pytest.MonkeyPatch,
    question: str,
) -> None:
    monkeypatch.setattr(graph_module, "_today", lambda: date(2026, 3, 19))

    filters = graph_module._extract_filters(question)

    assert filters is not None
    assert filters.date_from == date(2026, 3, 1)
    assert filters.date_to == date(2026, 3, 19)


def test_extract_filters_defaults_to_available_range_when_missing() -> None:
    filters = graph_module._extract_filters("What were total sales?")

    assert filters is not None
    assert filters.date_from == date(2026, 3, 1)
    assert filters.date_to == date(2026, 3, 7)


def test_extract_filters_supports_this_quarter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(graph_module, "_today", lambda: date(2026, 3, 19))

    filters = graph_module._extract_filters("Can you show average check for this quarter?")

    assert filters is not None
    assert filters.date_from == date(2026, 1, 1)
    assert filters.date_to == date(2026, 3, 19)


@pytest.mark.parametrize(
    "question",
    [
        "Ցույց տուր անցած տարվա միջին չեկը",
        "Ցույց տուր նախորդ տարվա միջին չեկը",
    ],
)
def test_extract_filters_supports_armenian_last_year_variants(
    monkeypatch: pytest.MonkeyPatch,
    question: str,
) -> None:
    monkeypatch.setattr(graph_module, "_today", lambda: date(2026, 3, 19))

    filters = graph_module._extract_filters(question)

    assert filters is not None
    assert filters.date_from == date(2025, 1, 1)
    assert filters.date_to == date(2025, 12, 31)


@pytest.mark.parametrize(
    ("llm_payload", "expected_order", "expected_status", "expected_report_id"),
    [
        (
            {
                "intent": "get_kpi",
                "report_id": "sales_total",
                "filters": {"date_from": "2026-03-01", "date_to": "2026-03-07"},
                "needs_clarification": False,
                "clarification_question": None,
                "confidence": 0.95,
                "reasoning_notes": "Matched sales_total and extracted date range.",
            },
            [
                "resolve_scope",
                "openai_interpret",
                "authorize_report",
                "run_report",
                "calc_metrics",
                "reason_over_results",
                "compose_output",
                "persist_run",
            ],
            RunStatus.COMPLETED,
            ReportType.SALES_TOTAL,
        ),
        (
            {
                "intent": "needs_clarification",
                "report_id": None,
                "filters": None,
                "needs_clarification": True,
                "clarification_question": "Please provide a date range.",
                "confidence": 0.52,
                "reasoning_notes": "Missing required date filter.",
            },
            [
                "resolve_scope",
                "openai_interpret",
                "authorize_report",
                "clarify",
                "persist_run",
            ],
            RunStatus.CLARIFY,
            None,
        ),
        (
            {
                "intent": "unsupported_request",
                "report_id": None,
                "filters": None,
                "needs_clarification": False,
                "clarification_question": None,
                "confidence": 0.18,
                "reasoning_notes": "Unsupported domain request.",
            },
            [
                "resolve_scope",
                "openai_interpret",
                "authorize_report",
                "reject",
                "persist_run",
            ],
            RunStatus.REJECTED,
            None,
        ),
    ],
)
def test_llm_interpretation_routes_based_on_model_output(
    monkeypatch: pytest.MonkeyPatch,
    llm_payload: dict[str, object],
    expected_order: list[str],
    expected_status: RunStatus,
    expected_report_id: ReportType | None,
) -> None:
    fake_client = _FakeLLMClient(output_text=json.dumps(llm_payload))
    monkeypatch.setattr(graph_module, "get_llm_client", lambda: fake_client)
    graph = build_agent_graph()
    payload = _initial_state("Interpret this request using model output.")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert len(fake_client.calls) >= 1
    assert order == expected_order
    assert final_state.status is expected_status
    assert final_state.selected_report_id is expected_report_id


def test_malformed_llm_output_routes_to_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = _FakeLLMClient(output_text='{"intent": "get_kpi"}')
    monkeypatch.setattr(graph_module, "get_llm_client", lambda: fake_client)
    graph = build_agent_graph()
    payload = _initial_state("Show KPI snapshot 2026-03-01 to 2026-03-07.")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "openai_interpret",
        "authorize_report",
        "reject",
        "persist_run",
    ]
    assert final_state.status is RunStatus.REJECTED
    assert "llm_interpretation_contract_invalid" in final_state.warnings


def test_llm_timeout_error_uses_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeout_error = LLMClientError(
        "OpenAI request timed out.",
        category=LLMErrorCategory.TIMEOUT,
        retryable=True,
    )
    fake_client = _FakeLLMClient(exc=timeout_error)
    monkeypatch.setattr(graph_module, "get_llm_client", lambda: fake_client)
    graph = build_agent_graph()
    payload = _initial_state("Show KPI snapshot 2026-03-01 to 2026-03-07.")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "openai_interpret",
        "authorize_report",
        "reject",
        "persist_run",
    ]
    assert final_state.status is RunStatus.REJECTED
    assert "interpretation_llm_fallback" in final_state.warnings


def test_llm_rate_limit_uses_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rate_limit_error = LLMClientError(
        "OpenAI rate limit reached.",
        category=LLMErrorCategory.RATE_LIMIT,
        retryable=True,
    )
    fake_client = _FakeLLMClient(exc=rate_limit_error)
    monkeypatch.setattr(graph_module, "get_llm_client", lambda: fake_client)
    graph = build_agent_graph()
    payload = _initial_state("Show KPI snapshot 2026-03-01 to 2026-03-07.")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "openai_interpret",
        "authorize_report",
        "reject",
        "persist_run",
    ]
    assert final_state.status is RunStatus.REJECTED
    assert "interpretation_rate_limit_fallback" in final_state.warnings


def test_missing_openai_key_uses_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback_called = False

    def _fallback_interpretation(_question: str) -> dict[str, object]:
        nonlocal fallback_called
        fallback_called = True
        return {
            "intent": "get_kpi",
            "report_id": "sales_total",
            "filters": {"date_from": "2026-03-01", "date_to": "2026-03-07"},
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.91,
            "reasoning_notes": "Fallback interpreter response.",
        }

    monkeypatch.setattr(graph_module, "_generate_interpretation_payload", _fallback_interpretation)
    monkeypatch.setattr(graph_module, "get_llm_client", _missing_openai_key)
    graph = build_agent_graph()

    final_state = AgentState.model_validate(
        graph.invoke(_initial_state("This path should use deterministic fallback."))
    )

    assert fallback_called is True
    assert final_state.status is RunStatus.COMPLETED
    assert final_state.selected_report_id is ReportType.SALES_TOTAL


def test_unambiguous_request_skips_llm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _llm_must_not_be_called() -> Any:
        raise AssertionError("LLM should not be called for deterministic requests.")

    monkeypatch.setattr(graph_module, "get_llm_client", _llm_must_not_be_called)
    graph = build_agent_graph()
    payload = _initial_state("What were total sales 2026-03-01 to 2026-03-07?")

    final_state = AgentState.model_validate(graph.invoke(payload))

    assert final_state.status is RunStatus.COMPLETED
    assert final_state.selected_report_id is ReportType.SALES_TOTAL
    assert "interpretation_rate_limit_fallback" not in final_state.warnings


def test_invalid_interpretation_output_routes_to_fallback_clarify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _invalid_interpretation_output(_question: str) -> dict[str, object]:
        return {
            "intent": "get_kpi",
            "report_id": "sales_total",
            "filters": {"date_from": "2026-03-01", "date_to": "2026-03-07"},
            "needs_clarification": False,
            "clarification_question": None,
            # Missing required "confidence" to force schema rejection.
        }

    monkeypatch.setattr(
        graph_module,
        "_generate_interpretation_payload",
        _invalid_interpretation_output,
    )
    graph = build_agent_graph()
    payload = _initial_state("What were total sales 2026-03-01 to 2026-03-07?")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "openai_interpret",
        "authorize_report",
        "clarify",
        "persist_run",
    ]
    assert final_state.status is RunStatus.CLARIFY
    assert final_state.needs_clarification is True
    assert final_state.clarification_question
    assert "interpretation_contract_invalid" in final_state.warnings


def test_unsupported_request_routes_to_reject() -> None:
    graph = build_agent_graph()
    payload = _initial_state("Show payroll tax trend 2026-03-01 to 2026-03-07.")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "openai_interpret",
        "authorize_report",
        "reject",
        "persist_run",
    ]
    assert final_state.status is RunStatus.REJECTED
    assert final_state.tool_responses.run_report is None
    assert "unsupported request" in (final_state.final_answer or "").lower()


def test_scope_denied_blocks_report_execution() -> None:
    graph = build_agent_graph()
    payload = _initial_state(
        "What were total sales 2026-03-01 to 2026-03-07?",
        deny_scope=True,
    )

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "openai_interpret",
        "authorize_report",
        "deny",
        "persist_run",
    ]
    assert final_state.status is RunStatus.DENIED
    assert final_state.tool_responses.run_report is None
    assert "access denied" in (final_state.final_answer or "").lower()


def test_disallowed_report_is_blocked_before_run_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_report_called = False

    def _restricted_scope(_request: Any) -> ResolveScopeResponse:
        return ResolveScopeResponse(
            status=AccessStatus.GRANTED,
            allowed_report_ids=[ReportType.ORDER_COUNT],
            denial_reason=None,
        )

    def _run_report_must_not_execute(_request: Any) -> Any:
        nonlocal run_report_called
        run_report_called = True
        raise AssertionError("run_report should not execute for disallowed report.")

    monkeypatch.setattr(graph_module, "resolve_scope_tool", _restricted_scope)
    monkeypatch.setattr(graph_module, "run_report_tool", _run_report_must_not_execute)
    graph = build_agent_graph()
    payload = _initial_state("What were total sales 2026-03-01 to 2026-03-07?")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "openai_interpret",
        "authorize_report",
        "deny",
        "persist_run",
    ]
    assert run_report_called is False
    assert final_state.status is RunStatus.DENIED
    assert final_state.tool_responses.run_report is None
    assert "authorization_blocked_report_not_allowed" in final_state.warnings


def test_run_report_exception_routes_to_fail_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _run_report_raises(_request: Any) -> Any:
        raise ValueError("Excel report file not found.")

    monkeypatch.setattr(graph_module, "run_report_tool", _run_report_raises)
    graph = build_agent_graph()
    payload = _initial_state("What were total sales 2026-03-01 to 2026-03-07?")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "openai_interpret",
        "authorize_report",
        "run_report",
        "fail",
        "persist_run",
    ]
    assert final_state.status is RunStatus.FAILED
    assert final_state.tool_responses.run_report is None
    assert "run_report_execution_failed" in final_state.warnings
    assert final_state.final_answer == "Run failed: report execution error."


def test_calc_mapping_failure_routes_to_fail_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_mapping_error(_run_response: Any) -> dict[str, Decimal]:
        raise ValueError("mapping failed")

    monkeypatch.setattr(graph_module, "map_report_response_to_base_metrics", _raise_mapping_error)
    graph = build_agent_graph()
    payload = _initial_state("What were total sales 2026-03-01 to 2026-03-07?")

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "openai_interpret",
        "authorize_report",
        "run_report",
        "calc_metrics",
        "fail",
        "persist_run",
    ]
    assert final_state.status is RunStatus.FAILED
    assert "calc_mapping_failed" in final_state.warnings


def test_persist_run_node_executes_finish_when_persistence_service_is_provided() -> None:
    class _PersistenceSpy:
        def __init__(self) -> None:
            self.finish_calls: list[dict[str, Any]] = []

        def finish_run(
            self,
            *,
            thread_id: Any,
            internal_run_id: Any,
            status: RunStatus,
            question: str,
            answer: str | None,
            error_message: str | None = None,
            error_code: str | None = None,
        ) -> FinishRunPersistenceResult:
            self.finish_calls.append(
                {
                    "thread_id": thread_id,
                    "internal_run_id": internal_run_id,
                    "status": status,
                    "question": question,
                    "answer": answer,
                    "error_message": error_message,
                    "error_code": error_code,
                }
            )
            return FinishRunPersistenceResult(warnings=["persistence_warning_finish"])

    spy = _PersistenceSpy()
    graph = build_agent_graph(persistence_service=spy)  # type: ignore[arg-type]
    payload = _initial_state("What were total sales 2026-03-01 to 2026-03-07?")
    payload["internal_thread_id"] = str(uuid4())
    payload["internal_run_id"] = str(uuid4())

    final_state = AgentState.model_validate(graph.invoke(payload))
    order = _node_order(graph, payload)

    assert order == [
        "resolve_scope",
        "openai_interpret",
        "authorize_report",
        "run_report",
        "calc_metrics",
        "reason_over_results",
        "compose_output",
        "persist_run",
    ]
    assert len(spy.finish_calls) == 2
    assert all(call["status"] is RunStatus.COMPLETED for call in spy.finish_calls)
    assert final_state.run_persisted is True
    assert "persistence_warning_finish" in final_state.warnings
