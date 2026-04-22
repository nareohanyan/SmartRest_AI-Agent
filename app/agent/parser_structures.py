from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from app.schemas.analysis import (
    BusinessQueryKind,
    DimensionName,
    ItemPerformanceMetric,
    MetricName,
    RankingMode,
)


@dataclass(frozen=True)
class ParsedDateRange:
    date_from: date
    date_to: date


@dataclass(frozen=True)
class ParsedBusinessQuery:
    kind: BusinessQueryKind
    item_metric: ItemPerformanceMetric | None = None
    item_query: str | None = None
    exclude_item_query: str | None = None


@dataclass(frozen=True)
class ParsedQuestion:
    normalized_question: str
    language: str
    date_range: ParsedDateRange | None
    has_business_signal: bool
    metric: MetricName | None
    dimension: DimensionName | None
    ranking_mode: RankingMode | None
    ranking_k: int
    wants_breakdown: bool
    wants_trend: bool
    wants_comparison: bool
    business_query: ParsedBusinessQuery | None


class ParserPolicyAction(str, Enum):
    PROCEED = "proceed"
    CLARIFY = "clarify"
    REJECT = "reject"


@dataclass(frozen=True)
class ParserPolicyDecision:
    action: ParserPolicyAction
    clarification_question: str | None = None
    reasoning_notes: str | None = None
