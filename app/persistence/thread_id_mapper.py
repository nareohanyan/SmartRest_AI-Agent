from __future__ import annotations

from uuid import UUID, uuid5

from app.persistence.errors import PersistenceValidationError

# Stable namespace for mapping external thread IDs into internal DB UUIDs.
THREAD_ID_NAMESPACE = UUID("a3e6f29f-0f5e-4fa7-bcc4-63d6f6b2db95")


def to_internal_thread_uuid(external_thread_id: str) -> UUID:
    normalized_thread_id = external_thread_id.strip()
    if not normalized_thread_id:
        raise PersistenceValidationError("thread_id must be a non-empty string.")

    return uuid5(THREAD_ID_NAMESPACE, normalized_thread_id)
