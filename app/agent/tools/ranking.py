"""Ranking tools for ordered business answers."""

from __future__ import annotations

from app.schemas.analysis import (
    RankedItemsResponse,
    RankingMode,
    RankItemsRequest,
    SortDirection,
)


def sort_items_tool(request: RankItemsRequest) -> RankedItemsResponse:
    reverse = request.ranking.direction is SortDirection.DESC
    ranked = sorted(request.items, key=lambda item: (item.value, item.label), reverse=reverse)
    return RankedItemsResponse(items=ranked)


def top_k_tool(request: RankItemsRequest) -> RankedItemsResponse:
    if request.ranking.mode is not RankingMode.TOP_K:
        raise ValueError("top_k_tool requires ranking.mode=top_k")
    ranked = sort_items_tool(request).items[: request.ranking.k]
    return RankedItemsResponse(items=ranked)


def bottom_k_tool(request: RankItemsRequest) -> RankedItemsResponse:
    if request.ranking.mode is not RankingMode.BOTTOM_K:
        raise ValueError("bottom_k_tool requires ranking.mode=bottom_k")
    ranked = sort_items_tool(request).items[: request.ranking.k]
    return RankedItemsResponse(items=ranked)
