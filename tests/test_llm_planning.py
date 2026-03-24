from __future__ import annotations

import pytest

from app.agent.llm.planning import (
    PlanningContractError,
    build_plan_messages,
    parse_plan_output_json,
)
from app.schemas.analysis import AnalysisIntent


def test_build_plan_messages_returns_system_and_user_entries() -> None:
    messages = build_plan_messages("Compare sales 2026-03-01 to 2026-03-07 vs previous")

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "completed_order_count" in messages[0]["content"]
    assert "branch" in messages[0]["content"]


def test_parse_plan_output_json_accepts_valid_payload() -> None:
    payload = """
    {
      "plan": {
        "intent": "comparison",
        "retrieval": {
          "mode": "total",
          "metric": "sales_total",
          "date_from": "2026-03-01",
          "date_to": "2026-03-07",
          "dimension": null
        },
        "compare_to_previous_period": true,
        "previous_period_retrieval": {
          "mode": "total",
          "metric": "sales_total",
          "date_from": "2026-02-22",
          "date_to": "2026-02-28",
          "dimension": null
        },
        "scalar_calculations": [],
        "include_moving_average": false,
        "moving_average_window": 3,
        "include_trend_slope": false,
        "ranking": null,
        "needs_clarification": false,
        "clarification_question": null,
        "reasoning_notes": "Comparison intent."
      },
      "confidence": 0.92
    }
    """
    envelope = parse_plan_output_json(payload)

    assert envelope.plan.intent is AnalysisIntent.COMPARISON
    assert envelope.confidence == 0.92


def test_parse_plan_output_json_rejects_invalid_payload() -> None:
    with pytest.raises(PlanningContractError):
        parse_plan_output_json('{"plan": {"intent": "comparison"}, "confidence": 0.8}')


def test_parse_plan_output_json_accepts_smalltalk_payload() -> None:
    payload = """
    {
      "plan": {
        "intent": "smalltalk",
        "retrieval": null,
        "compare_to_previous_period": false,
        "previous_period_retrieval": null,
        "scalar_calculations": [],
        "include_moving_average": false,
        "moving_average_window": 3,
        "include_trend_slope": false,
        "ranking": null,
        "needs_clarification": false,
        "clarification_question": null,
        "reasoning_notes": "Greeting input."
      },
      "confidence": 0.9
    }
    """
    envelope = parse_plan_output_json(payload)

    assert envelope.plan.intent is AnalysisIntent.SMALLTALK
