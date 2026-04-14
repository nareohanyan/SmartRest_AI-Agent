"""Unified tool exports.

This package-level module preserves legacy imports such as:
`from app.agent.tools import compute_metrics_tool`
while also exposing new dynamic-planning tools.
"""

from app.agent.calc_tools import compute_metrics_tool
from app.agent.report_tools import (
    get_report_definition_tool,
    list_reports_tool,
    resolve_scope_tool,
    run_report_tool,
)
from app.agent.tools.analytics import (
    attach_breakdown_share_tool,
    compute_scalar_metrics_tool,
    materialize_previous_period_metrics,
    materialize_timeseries_as_base_metrics,
    moving_average_tool,
    trend_slope_tool,
)
from app.agent.tools.business_insights import (
    fetch_customer_summary_tool,
    fetch_item_performance_tool,
    fetch_receipt_summary_tool,
)
from app.agent.tools.ranking import bottom_k_tool, sort_items_tool, top_k_tool
from app.agent.tools.retrieval import (
    fetch_breakdown_tool,
    fetch_timeseries_tool,
    fetch_total_metric_tool,
)

__all__ = [
    "attach_breakdown_share_tool",
    "bottom_k_tool",
    "compute_metrics_tool",
    "compute_scalar_metrics_tool",
    "fetch_breakdown_tool",
    "fetch_customer_summary_tool",
    "fetch_item_performance_tool",
    "fetch_receipt_summary_tool",
    "fetch_timeseries_tool",
    "fetch_total_metric_tool",
    "get_report_definition_tool",
    "list_reports_tool",
    "materialize_previous_period_metrics",
    "materialize_timeseries_as_base_metrics",
    "moving_average_tool",
    "resolve_scope_tool",
    "run_report_tool",
    "sort_items_tool",
    "top_k_tool",
    "trend_slope_tool",
]
