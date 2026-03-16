from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx
import pytest
from openai import APIStatusError, APITimeoutError, AuthenticationError

from app.agent.llm.client import OpenAILLMClient, RetryPolicy
from app.agent.llm.exceptions import LLMClientError
from app.schemas.agent import LLMErrorCategory


class _FakeCompletion:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text


class _FakeResponsesAPI:
    def __init__(self, side_effects: list[object]) -> None:
        self._side_effects = side_effects
        self.calls: list[dict[str, Any]] = []

    def create(
        self,
        *,
        model: str,
        input: Sequence[dict[str, str]],
        timeout: float,
    ) -> Any:
        self.calls.append({"model": model, "input": list(input), "timeout": timeout})
        if not self._side_effects:
            raise AssertionError("No fake response configured.")

        outcome = self._side_effects.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeOpenAIClient:
    def __init__(self, side_effects: list[object]) -> None:
        self.responses = _FakeResponsesAPI(side_effects)


def _openai_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/responses")


def _openai_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code=status_code, request=_openai_request())


def test_generate_text_returns_trimmed_output_and_uses_configured_timeout() -> None:
    fake_client = _FakeOpenAIClient([_FakeCompletion("  completed text  ")])
    client = OpenAILLMClient(
        api_key="test-key",
        model="gpt-test",
        timeout_seconds=12.0,
        retry_policy=RetryPolicy(max_attempts=1),
        openai_client=fake_client,
    )

    output = client.generate_text(messages=[{"role": "user", "content": "hello"}])

    assert output == "completed text"
    assert fake_client.responses.calls == [
        {
            "model": "gpt-test",
            "input": [{"role": "user", "content": "hello"}],
            "timeout": 12.0,
        }
    ]


def test_generate_text_retries_timeout_error_and_recovers() -> None:
    fake_client = _FakeOpenAIClient(
        [
            APITimeoutError(request=_openai_request()),
            _FakeCompletion("ok"),
        ]
    )
    sleep_calls: list[float] = []
    client = OpenAILLMClient(
        api_key="test-key",
        model="gpt-test",
        timeout_seconds=8.0,
        retry_policy=RetryPolicy(
            max_attempts=3,
            initial_delay_seconds=0.5,
            max_delay_seconds=2.0,
            jitter_ratio=0.0,
        ),
        openai_client=fake_client,
        sleep=sleep_calls.append,
    )

    output = client.generate_text(messages=[{"role": "user", "content": "hello"}])

    assert output == "ok"
    assert len(fake_client.responses.calls) == 2
    assert sleep_calls == [0.5]


def test_generate_text_maps_auth_error_to_non_retryable_category() -> None:
    fake_client = _FakeOpenAIClient(
        [
            AuthenticationError(
                "invalid api key",
                response=_openai_response(401),
                body={},
            )
        ]
    )
    client = OpenAILLMClient(
        api_key="test-key",
        model="gpt-test",
        timeout_seconds=8.0,
        retry_policy=RetryPolicy(max_attempts=3, jitter_ratio=0.0),
        openai_client=fake_client,
    )

    with pytest.raises(LLMClientError) as exc_info:
        client.generate_text(messages=[{"role": "user", "content": "hello"}])

    assert exc_info.value.category is LLMErrorCategory.AUTHENTICATION
    assert exc_info.value.retryable is False
    assert len(fake_client.responses.calls) == 1


def test_generate_text_maps_5xx_errors_and_stops_after_retry_limit() -> None:
    server_error = APIStatusError(
        "upstream unavailable",
        response=_openai_response(503),
        body={},
    )
    fake_client = _FakeOpenAIClient([server_error, server_error])
    sleep_calls: list[float] = []
    client = OpenAILLMClient(
        api_key="test-key",
        model="gpt-test",
        timeout_seconds=8.0,
        retry_policy=RetryPolicy(
            max_attempts=2,
            initial_delay_seconds=0.2,
            max_delay_seconds=2.0,
            jitter_ratio=0.0,
        ),
        openai_client=fake_client,
        sleep=sleep_calls.append,
    )

    with pytest.raises(LLMClientError) as exc_info:
        client.generate_text(messages=[{"role": "user", "content": "hello"}])

    assert exc_info.value.category is LLMErrorCategory.SERVER
    assert exc_info.value.retryable is True
    assert len(fake_client.responses.calls) == 2
    assert sleep_calls == [0.2]
