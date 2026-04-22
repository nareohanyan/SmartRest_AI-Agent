from __future__ import annotations

import json

from app.agent.llm.response import RESPONSE_COMPOSER_SYSTEM_PROMPT, build_response_messages


def test_build_response_messages_returns_system_and_user_entries() -> None:
    messages = build_response_messages(
        {
            "route": "smalltalk",
            "language_hint": "hy",
            "user_question": "բարև",
            "factual_answer": "Բարև։ Կարող եմ օգնել SmartRest անալիտիկ հարցերով։",
            "policy_reason": None,
            "warnings": [],
        }
    )

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == RESPONSE_COMPOSER_SYSTEM_PROMPT
    assert messages[1]["role"] == "user"


def test_build_response_messages_embeds_json_context() -> None:
    messages = build_response_messages(
        {
            "route": "safe_answer",
            "language_hint": "en",
            "user_question": "hello",
            "factual_answer": "I can help with SmartRest analytics.",
            "policy_reason": "unsupported_safe_answer",
            "warnings": ["planner_llm_error_fallback"],
        }
    )
    payload = json.loads(messages[1]["content"])

    assert payload["route"] == "safe_answer"
    assert payload["language_hint"] == "en"
    assert payload["policy_reason"] == "unsupported_safe_answer"
    assert payload["warnings"] == ["planner_llm_error_fallback"]
