from __future__ import annotations

import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol, cast

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    OpenAI,
    RateLimitError,
)

from app.agent.llm.exceptions import LLMClientError
from app.core.config import get_settings
from app.schemas.agent import LLMErrorCategory

LLMMessage = dict[str, str]


class LLMClient(Protocol):
    def generate_text(
        self,
        *,
        messages: Sequence[LLMMessage],
        model: str | None = None,
    ) -> str:
        """Generate text completion from chat-style messages."""


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_delay_seconds: float = 0.25
    backoff_multiplier: float = 2.0
    max_delay_seconds: float = 2.0
    jitter_ratio: float = 0.1

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")
        if self.initial_delay_seconds < 0:
            raise ValueError("initial_delay_seconds cannot be negative.")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be at least 1.")
        if self.max_delay_seconds < 0:
            raise ValueError("max_delay_seconds cannot be negative.")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between 0 and 1.")


class _OpenAIResponsesAPI(Protocol):
    def create(
        self,
        *,
        model: str,
        input: Sequence[LLMMessage],
        timeout: float,
    ) -> Any:
        ...

class _OpenAIClient(Protocol):
    responses: _OpenAIResponsesAPI


class OpenAILLMClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        retry_policy: RetryPolicy | None = None,
        openai_client: _OpenAIClient | None = None,
        sleep: Callable[[float], None] = time.sleep,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OpenAI API key is required.")
        if not model.strip():
            raise ValueError("OpenAI model is required.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")

        self._model = model
        self._timeout_seconds = timeout_seconds
        self._retry_policy = retry_policy or RetryPolicy()
        self._sleep = sleep
        self._random_value = random_value
        self._client: _OpenAIClient
        if openai_client is not None:
            self._client = openai_client
        else:
            self._client = cast(_OpenAIClient, OpenAI(api_key=api_key))

    def generate_text(
        self,
        *,
        messages: Sequence[LLMMessage],
        model: str | None = None,
    ) -> str:
        attempt = 0
        selected_model = model or self._model

        while True:
            try:
                response = self._client.responses.create(
                    model=selected_model,
                    input=messages,
                    timeout=self._timeout_seconds,
                )
                return _extract_output_text(response)
            except LLMClientError:
                raise
            except Exception as exc:
                normalized_error = normalize_llm_error(exc)
                attempt += 1
                if not normalized_error.retryable or attempt >= self._retry_policy.max_attempts:
                    raise normalized_error from exc

                self._sleep(self._retry_delay(attempt))

    def _retry_delay(self, attempt: int) -> float:
        base_delay = self._retry_policy.initial_delay_seconds * (
            self._retry_policy.backoff_multiplier ** (attempt - 1)
        )
        bounded_delay = min(base_delay, self._retry_policy.max_delay_seconds)
        if bounded_delay == 0 or self._retry_policy.jitter_ratio == 0:
            return bounded_delay

        jitter = bounded_delay * self._retry_policy.jitter_ratio * self._random_value()
        return bounded_delay + jitter


def _extract_output_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if not isinstance(output_text, str) or not output_text.strip():
        raise LLMClientError(
            "OpenAI response did not include output text.",
            category=LLMErrorCategory.UNKNOWN,
            retryable=False,
        )
    return output_text.strip()


def normalize_llm_error(exc: Exception) -> LLMClientError:
    """Map OpenAI SDK failures into controlled client categories."""
    if isinstance(exc, LLMClientError):
        return exc
    if isinstance(exc, APITimeoutError):
        return LLMClientError(
            "OpenAI request timed out.",
            category=LLMErrorCategory.TIMEOUT,
            retryable=True,
        )
    if isinstance(exc, APIConnectionError):
        return LLMClientError(
            "OpenAI connection failed.",
            category=LLMErrorCategory.CONNECTION,
            retryable=True,
        )
    if isinstance(exc, RateLimitError):
        return LLMClientError(
            "OpenAI rate limit reached.",
            category=LLMErrorCategory.RATE_LIMIT,
            retryable=True,
            status_code=429,
        )
    if isinstance(exc, AuthenticationError):
        return LLMClientError(
            "OpenAI authentication failed.",
            category=LLMErrorCategory.AUTHENTICATION,
            retryable=False,
            status_code=401,
        )
    if isinstance(exc, BadRequestError):
        return LLMClientError(
            "OpenAI rejected the request payload.",
            category=LLMErrorCategory.BAD_REQUEST,
            retryable=False,
            status_code=400,
        )
    if isinstance(exc, APIStatusError):
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int) and status_code >= 500:
            return LLMClientError(
                "OpenAI service unavailable.",
                category=LLMErrorCategory.SERVER,
                retryable=True,
                status_code=status_code,
            )
        if status_code == 429:
            return LLMClientError(
                "OpenAI rate limit reached.",
                category=LLMErrorCategory.RATE_LIMIT,
                retryable=True,
                status_code=status_code,
            )
        if status_code in (401, 403):
            return LLMClientError(
                "OpenAI authentication failed.",
                category=LLMErrorCategory.AUTHENTICATION,
                retryable=False,
                status_code=status_code,
            )
        return LLMClientError(
            "OpenAI rejected the request payload.",
            category=LLMErrorCategory.BAD_REQUEST,
            retryable=False,
            status_code=status_code if isinstance(status_code, int) else None,
        )
    if isinstance(exc, APIError):
        return LLMClientError(
            "OpenAI request failed.",
            category=LLMErrorCategory.UNKNOWN,
            retryable=False,
        )
    return LLMClientError(
        "Unexpected LLM client failure.",
        category=LLMErrorCategory.UNKNOWN,
        retryable=False,
    )


@lru_cache(maxsize=1)
def get_llm_client() -> OpenAILLMClient:
    """Build the default OpenAI-backed LLM client from app settings."""
    settings = get_settings()
    api_key = settings.openai_api_key
    if api_key is None or not api_key.strip():
        raise ValueError("OPENAI_API_KEY is not configured.")

    retry_policy = RetryPolicy(
        max_attempts=settings.openai_retry_max_attempts,
        initial_delay_seconds=settings.openai_retry_initial_delay_seconds,
        max_delay_seconds=settings.openai_retry_max_delay_seconds,
    )
    return OpenAILLMClient(
        api_key=api_key,
        model=settings.openai_model,
        timeout_seconds=settings.openai_timeout_seconds,
        retry_policy=retry_policy,
    )
