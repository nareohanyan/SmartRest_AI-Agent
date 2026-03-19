from __future__ import annotations

import pytest

from app.agent.llm.prompts import (
    InterpretationContractError,
    build_interpret_request_messages,
    parse_interpretation_output_json,
    validate_interpretation_output,
)
from app.schemas.agent import IntentType
from app.schemas.reports import ReportType


def test_build_interpret_request_messages_returns_system_and_user_entries() -> None:
    messages = build_interpret_request_messages("What were total sales yesterday?")

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert 'The user question language is "English".' in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": "What were total sales yesterday?"}


def test_build_interpret_request_messages_adds_armenian_language_policy() -> None:
    messages = build_interpret_request_messages("Ընդհանուր վաճառքը 2024-07-12 to 2024-07-20?")

    assert messages[0]["role"] == "system"
    assert 'The user question language is "Armenian".' in messages[0]["content"]


def test_build_interpret_request_messages_adds_russian_language_policy() -> None:
    messages = build_interpret_request_messages("Покажи общие продажи 2024-07-12 to 2024-07-20.")

    assert messages[0]["role"] == "system"
    assert 'The user question language is "Russian".' in messages[0]["content"]


def test_validate_interpretation_output_accepts_valid_supported_payload() -> None:
    interpretation = validate_interpretation_output(
        {
            "intent": "get_kpi",
            "report_id": "sales_total",
            "filters": {"date_from": "2026-03-01", "date_to": "2026-03-07"},
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.9,
            "reasoning_notes": "Matched sales_total and extracted full date range.",
        }
    )

    assert interpretation.intent is IntentType.GET_KPI
    assert interpretation.report_id is ReportType.SALES_TOTAL
    assert interpretation.needs_clarification is False


def test_validate_interpretation_output_rejects_missing_required_fields() -> None:
    with pytest.raises(InterpretationContractError):
        validate_interpretation_output(
            {
                "intent": "get_kpi",
                "report_id": "sales_total",
                "filters": {"date_from": "2026-03-01", "date_to": "2026-03-07"},
                "needs_clarification": False,
                "clarification_question": None,
                # Missing confidence
            }
        )


def test_validate_interpretation_output_accepts_small_talk_payload() -> None:
    interpretation = validate_interpretation_output(
        {
            "intent": "small_talk",
            "report_id": None,
            "filters": None,
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.95,
            "reasoning_notes": "Greeting message.",
        }
    )

    assert interpretation.intent is IntentType.SMALL_TALK
    assert interpretation.report_id is None
    assert interpretation.filters is None


def test_parse_interpretation_output_json_rejects_non_json_text() -> None:
    with pytest.raises(InterpretationContractError):
        parse_interpretation_output_json("this is not json")
