from __future__ import annotations

from app.agent.services.live_business_tools import LiveBusinessToolsService
from app.core.config import get_settings
from app.core.runtime_policy import require_strict_backend_mode
from app.schemas.analysis import (
    CustomerSummaryRequest,
    CustomerSummaryResponse,
    ItemPerformanceRequest,
    ItemPerformanceResponse,
    ReceiptSummaryRequest,
    ReceiptSummaryResponse,
)


def fetch_item_performance_tool(request: ItemPerformanceRequest) -> ItemPerformanceResponse:
    _require_live_business_backend()
    return LiveBusinessToolsService().get_item_performance(request)


def fetch_customer_summary_tool(request: CustomerSummaryRequest) -> CustomerSummaryResponse:
    _require_live_business_backend()
    return LiveBusinessToolsService().get_customer_summary(request)


def fetch_receipt_summary_tool(request: ReceiptSummaryRequest) -> ReceiptSummaryResponse:
    _require_live_business_backend()
    return LiveBusinessToolsService().get_receipt_summary(request)


def _require_live_business_backend() -> None:
    settings = get_settings()
    require_strict_backend_mode(
        settings=settings,
        field_name="analytics_backend_mode",
        actual_mode=settings.analytics_backend_mode,
    )
