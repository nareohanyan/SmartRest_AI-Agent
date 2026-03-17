from __future__ import annotations

from uuid import UUID

import pytest

from app.persistence.errors import PersistenceValidationError
from app.persistence.thread_id_mapper import to_internal_thread_uuid


def test_to_internal_thread_uuid_is_deterministic_for_same_input() -> None:
    first = to_internal_thread_uuid("thread-123")
    second = to_internal_thread_uuid("thread-123")

    assert isinstance(first, UUID)
    assert first == second


def test_to_internal_thread_uuid_differs_for_different_inputs() -> None:
    first = to_internal_thread_uuid("thread-a")
    second = to_internal_thread_uuid("thread-b")

    assert first != second


def test_to_internal_thread_uuid_normalizes_whitespace() -> None:
    first = to_internal_thread_uuid(" thread-xyz ")
    second = to_internal_thread_uuid("thread-xyz")

    assert first == second


@pytest.mark.parametrize("thread_id", ["", " ", "   "])
def test_to_internal_thread_uuid_rejects_blank_values(thread_id: str) -> None:
    with pytest.raises(PersistenceValidationError):
        to_internal_thread_uuid(thread_id)
