from __future__ import annotations

from typing import Any

__all__ = [
    "LiveAnalyticsService",
    "LiveAnalyticsUnsupportedError",
    "get_live_analytics_service",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from app.agent.services.live_analytics import (
            LiveAnalyticsService,
            LiveAnalyticsUnsupportedError,
            get_live_analytics_service,
        )

        exports = {
            "LiveAnalyticsService": LiveAnalyticsService,
            "LiveAnalyticsUnsupportedError": LiveAnalyticsUnsupportedError,
            "get_live_analytics_service": get_live_analytics_service,
        }
        return exports[name]
    raise AttributeError(name)
