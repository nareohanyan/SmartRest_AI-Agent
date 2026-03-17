from typing import Literal

from app.schemas.agent import RunStatus

DbRunStatus = Literal["started", "completed", "failed", "clarification_needed"]

def map_runtime_status_to_db(status: RunStatus) -> tuple[DbRunStatus, str | None]:
    if status is RunStatus.RUNNING:
        return "started", None
    if status is RunStatus.COMPLETED:
        return "completed", None
    if status is RunStatus.CLARIFY:
        return "clarification_needed", None
    if status is RunStatus.FAILED:
        return "failed", "runtime_failed"
    if status is RunStatus.REJECTED:
        return "failed", "rejected"
    if status is RunStatus.DENIED:
        return "failed", "denied"
    raise ValueError(f"Unsupported runtime status: {status}")
