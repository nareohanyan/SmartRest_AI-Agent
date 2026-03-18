"""Agent runtime package."""

from __future__ import annotations

from typing import Any

from app.agent.calc_tools import compute_metrics_tool
from app.agent.report_tools import (
    get_report_definition_tool,
    list_reports_tool,
    resolve_scope_tool,
    run_report_tool,
)
from app.persistence.runtime_persistence import RuntimePersistenceService


def build_agent_graph(
    *,
    persistence_service: RuntimePersistenceService | None = None,
) -> Any:
    """Lazily import graph runtime to avoid hard dependency at package import time."""
    from app.agent.graph import build_agent_graph as _build_agent_graph

    return _build_agent_graph(persistence_service=persistence_service)


__all__ = [
    "build_agent_graph",
    "compute_metrics_tool",
    "get_report_definition_tool",
    "list_reports_tool",
    "resolve_scope_tool",
    "run_report_tool",
]
