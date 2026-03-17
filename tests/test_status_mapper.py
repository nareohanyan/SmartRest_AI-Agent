from __future__ import annotations

import pytest

from app.persistence.status_mapper import map_runtime_status_to_db
from app.schemas.agent import RunStatus


@pytest.mark.parametrize(
    ("runtime_status", "expected_db_status", "expected_error_code"),
    [
        (RunStatus.RUNNING, "started", None),
        (RunStatus.COMPLETED, "completed", None),
        (RunStatus.CLARIFY, "clarification_needed", None),
        (RunStatus.FAILED, "failed", "runtime_failed"),
        (RunStatus.REJECTED, "failed", "rejected"),
        (RunStatus.DENIED, "failed", "denied"),
    ],
)
def test_map_runtime_status_to_db(
    runtime_status: RunStatus,
    expected_db_status: str,
    expected_error_code: str | None,
) -> None:
    db_status, error_code = map_runtime_status_to_db(runtime_status)

    assert db_status == expected_db_status
    assert error_code == expected_error_code
