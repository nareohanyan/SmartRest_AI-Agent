from __future__ import annotations

from app.schemas.agent import LLMErrorCategory


class LLMClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        category: LLMErrorCategory,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.status_code = status_code
