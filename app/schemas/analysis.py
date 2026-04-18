from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.base import SchemaModel
from app.schemas.calculations import CalculationSpec
from app.schemas.reports import ReportType


class MetricName(str, Enum):
    SALES_TOTAL = "sales_total"
    GROSS_SALES_TOTAL = "gross_sales_total"
    ORDER_COUNT = "order_count"
    AVERAGE_CHECK = "average_check"
    COMPLETED_ORDER_COUNT = "completed_order_count"
    DISCOUNTED_ORDER_COUNT = "discounted_order_count"
    DISCOUNTED_ORDER_SHARE = "discounted_order_share"
    CANCELED_ORDER_COUNT = "canceled_order_count"
    REFUND_AMOUNT = "refund_amount"
    DISCOUNT_AMOUNT = "discount_amount"
    REFUND_RATE = "refund_rate"
    DISCOUNT_SHARE = "discount_share"
    DELIVERY_ORDER_COUNT = "delivery_order_count"
    DINE_IN_ORDER_COUNT = "dine_in_order_count"
    QUANTITY_SOLD = "quantity_sold"
    ITEMS_PER_ORDER = "items_per_order"


class DimensionName(str, Enum):
    BRANCH = "branch"
    SOURCE = "source"
    DAY = "day"
    HOUR = "hour"
    WEEKDAY = "weekday"
    PAYMENT_METHOD = "payment_method"
    CATEGORY = "category"
    CASHIER = "cashier"


class RetrievalMode(str, Enum):
    TOTAL = "total"
    BREAKDOWN = "breakdown"
    TIMESERIES = "timeseries"


class AnalysisIntent(str, Enum):
    METRIC_TOTAL = "metric_total"
    BREAKDOWN = "breakdown"
    TREND = "trend"
    COMPARISON = "comparison"
    RANKING = "ranking"
    SMALLTALK = "smalltalk"
    CLARIFY = "clarify"
    UNSUPPORTED = "unsupported"


class ToolWarningCode(str, Enum):
    ZERO_TOTAL_NO_SHARE = "zero_total_no_share"


class SortDirection(str, Enum):
    DESC = "desc"
    ASC = "asc"


class RankingMode(str, Enum):
    TOP_K = "top_k"
    BOTTOM_K = "bottom_k"


class ItemPerformanceMetric(str, Enum):
    ITEM_REVENUE = "item_revenue"
    QUANTITY_SOLD = "quantity_sold"
    DISTINCT_ORDERS = "distinct_orders"


class BusinessQueryKind(str, Enum):
    ITEM_PERFORMANCE = "item_performance"
    CUSTOMER_SUMMARY = "customer_summary"
    RECEIPT_SUMMARY = "receipt_summary"


def _validate_optional_date_range(
    date_from: date | None,
    date_to: date | None,
    *,
    context: str,
) -> None:
    if (date_from is None) != (date_to is None):
        raise ValueError(f"{context} requires both date_from and date_to when either is set")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValueError("date_from must be on or before date_to")


class RankingSpec(SchemaModel):
    mode: RankingMode
    k: int = Field(default=3, ge=1, le=20)
    metric_key: str = Field(min_length=1)
    direction: SortDirection | None = None

    @model_validator(mode="after")
    def apply_default_direction(self) -> RankingSpec:
        if self.direction is None:
            self.direction = (
                SortDirection.DESC if self.mode is RankingMode.TOP_K else SortDirection.ASC
            )
        return self


class RetrievalSpec(SchemaModel):
    mode: RetrievalMode
    metric: MetricName
    date_from: date | None = None
    date_to: date | None = None
    dimension: DimensionName | None = None

    @model_validator(mode="after")
    def validate_range_and_dimension(self) -> RetrievalSpec:
        _validate_optional_date_range(
            self.date_from,
            self.date_to,
            context="retrieval",
        )
        if self.mode is RetrievalMode.BREAKDOWN and self.dimension is None:
            raise ValueError("breakdown retrieval requires dimension")
        if self.mode is RetrievalMode.TOTAL and self.dimension is not None:
            raise ValueError("total retrieval must not specify dimension")
        return self


class AnalysisPlan(SchemaModel):
    intent: AnalysisIntent
    retrieval: RetrievalSpec | None = None
    business_query: BusinessQuerySpec | None = None
    compare_to_previous_period: bool = False
    previous_period_retrieval: RetrievalSpec | None = None
    scalar_calculations: list[CalculationSpec] = Field(default_factory=list)
    include_moving_average: bool = False
    moving_average_window: int = Field(default=3, ge=2, le=30)
    include_trend_slope: bool = False
    ranking: RankingSpec | None = None
    needs_clarification: bool = False
    clarification_question: str | None = None
    reasoning_notes: str | None = None

    @model_validator(mode="after")
    def validate_clarification_contract(self) -> AnalysisPlan:
        if self.needs_clarification and not self.clarification_question:
            raise ValueError("clarification_question is required when needs_clarification=true")
        if self.intent is AnalysisIntent.CLARIFY and not self.needs_clarification:
            raise ValueError("clarify intent requires needs_clarification=true")
        if (
            self.intent
            not in {AnalysisIntent.CLARIFY, AnalysisIntent.UNSUPPORTED, AnalysisIntent.SMALLTALK}
            and self.retrieval is None
            and self.business_query is None
        ):
            raise ValueError("retrieval or business_query is required for supported plans")
        if self.compare_to_previous_period and self.previous_period_retrieval is None:
            raise ValueError(
                "previous_period_retrieval is required when compare_to_previous_period=true"
            )
        return self


class RetrievalScope(SchemaModel):
    profile_id: int = Field(ge=1)
    branch_ids: list[int] = Field(default_factory=list)
    source: str | None = Field(default=None, min_length=1)
    timezone: str | None = Field(default=None, min_length=1)


class TotalMetricRequest(SchemaModel):
    metric: MetricName
    date_from: date | None = None
    date_to: date | None = None
    scope: RetrievalScope | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> TotalMetricRequest:
        _validate_optional_date_range(self.date_from, self.date_to, context="total metric request")
        return self


class TotalMetricResponse(SchemaModel):
    metric: MetricName
    date_from: date | None = None
    date_to: date | None = None
    value: Decimal
    base_metrics: dict[str, Decimal] = Field(default_factory=dict)
    warnings: list[ToolWarningCode] = Field(default_factory=list)


class BreakdownItem(SchemaModel):
    label: str = Field(min_length=1)
    value: Decimal
    share_percent: Decimal | None = None


class BreakdownRequest(SchemaModel):
    metric: MetricName
    dimension: DimensionName
    date_from: date | None = None
    date_to: date | None = None
    scope: RetrievalScope | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> BreakdownRequest:
        _validate_optional_date_range(self.date_from, self.date_to, context="breakdown request")
        return self


class BreakdownResponse(SchemaModel):
    metric: MetricName
    dimension: DimensionName
    date_from: date | None = None
    date_to: date | None = None
    items: list[BreakdownItem] = Field(default_factory=list)
    total_value: Decimal
    warnings: list[ToolWarningCode] = Field(default_factory=list)


class TimeseriesPoint(SchemaModel):
    bucket: date
    value: Decimal


class TimeseriesRequest(SchemaModel):
    metric: MetricName
    date_from: date | None = None
    date_to: date | None = None
    dimension: DimensionName = DimensionName.DAY
    scope: RetrievalScope | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> TimeseriesRequest:
        _validate_optional_date_range(self.date_from, self.date_to, context="timeseries request")
        return self


class TimeseriesResponse(SchemaModel):
    metric: MetricName
    dimension: DimensionName
    date_from: date | None = None
    date_to: date | None = None
    points: list[TimeseriesPoint] = Field(default_factory=list)
    warnings: list[ToolWarningCode] = Field(default_factory=list)


class ItemPerformanceItem(SchemaModel):
    menu_item_id: int | None = Field(default=None, ge=1)
    name: str = Field(min_length=1)
    value: Decimal


class ItemPerformanceRequest(SchemaModel):
    metric: ItemPerformanceMetric
    date_from: date | None = None
    date_to: date | None = None
    limit: int = Field(default=10, ge=1, le=50)
    ranking_mode: RankingMode = RankingMode.TOP_K
    item_query: str | None = Field(default=None, min_length=1)
    scope: RetrievalScope | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> ItemPerformanceRequest:
        _validate_optional_date_range(
            self.date_from,
            self.date_to,
            context="item performance request",
        )
        return self


class BusinessQuerySpec(SchemaModel):
    kind: BusinessQueryKind
    date_from: date | None = None
    date_to: date | None = None
    item_metric: ItemPerformanceMetric | None = None
    item_query: str | None = Field(default=None, min_length=1)
    limit: int = Field(default=10, ge=1, le=50)
    ranking_mode: RankingMode = RankingMode.TOP_K

    @model_validator(mode="after")
    def validate_contract(self) -> BusinessQuerySpec:
        _validate_optional_date_range(
            self.date_from,
            self.date_to,
            context="business query",
        )
        if self.kind is BusinessQueryKind.ITEM_PERFORMANCE and self.item_metric is None:
            raise ValueError("item_metric is required for item_performance business queries")
        if self.kind is not BusinessQueryKind.ITEM_PERFORMANCE and self.item_metric is not None:
            raise ValueError("item_metric is only valid for item_performance business queries")
        return self


class ItemPerformanceResponse(SchemaModel):
    metric: ItemPerformanceMetric
    date_from: date | None = None
    date_to: date | None = None
    ranking_mode: RankingMode
    items: list[ItemPerformanceItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CustomerSummaryRequest(SchemaModel):
    date_from: date | None = None
    date_to: date | None = None
    scope: RetrievalScope | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> CustomerSummaryRequest:
        _validate_optional_date_range(
            self.date_from,
            self.date_to,
            context="customer summary request",
        )
        return self


class CustomerSummaryResponse(SchemaModel):
    date_from: date | None = None
    date_to: date | None = None
    unique_clients: int = Field(ge=0)
    identified_order_count: int = Field(ge=0)
    total_order_count: int = Field(ge=0)
    average_orders_per_identified_client: Decimal
    warnings: list[str] = Field(default_factory=list)


class ReceiptSummaryRequest(SchemaModel):
    date_from: date | None = None
    date_to: date | None = None
    scope: RetrievalScope | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> ReceiptSummaryRequest:
        _validate_optional_date_range(
            self.date_from,
            self.date_to,
            context="receipt summary request",
        )
        return self


class ReceiptSummaryResponse(SchemaModel):
    date_from: date | None = None
    date_to: date | None = None
    receipt_count: int = Field(ge=0)
    linked_order_count: int = Field(ge=0)
    status_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class MovingAveragePoint(SchemaModel):
    bucket: date
    value: Decimal | None


class MovingAverageRequest(SchemaModel):
    points: list[TimeseriesPoint] = Field(min_length=1)
    window_size: int = Field(ge=2, le=30)

    @model_validator(mode="after")
    def validate_window(self) -> MovingAverageRequest:
        if self.window_size > len(self.points):
            raise ValueError("window_size cannot exceed number of points")
        return self


class MovingAverageResponse(SchemaModel):
    points: list[MovingAveragePoint] = Field(default_factory=list)
    warnings: list[ToolWarningCode] = Field(default_factory=list)


class TrendSlopeRequest(SchemaModel):
    points: list[TimeseriesPoint] = Field(min_length=2)


class TrendSlopeResponse(SchemaModel):
    slope_per_day: Decimal
    direction: Literal["up", "down", "flat"]
    warnings: list[ToolWarningCode] = Field(default_factory=list)


class RankItemsRequest(SchemaModel):
    items: list[BreakdownItem] = Field(min_length=1)
    ranking: RankingSpec


class RankedItemsResponse(SchemaModel):
    items: list[BreakdownItem] = Field(default_factory=list)


class LegacyReportTask(SchemaModel):
    task_id: str = Field(min_length=1)
    user_subquery: str = Field(min_length=1)
    metric: MetricName | None = None
    date_from: date | None = None
    date_to: date | None = None
    supported: bool = True
    report_id: ReportType | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_supported_task(self) -> LegacyReportTask:
        if self.supported:
            if self.metric is None or self.date_from is None or self.date_to is None:
                raise ValueError("supported legacy report tasks require metric and date range")
            if self.date_from > self.date_to:
                raise ValueError("date_from must be on or before date_to")
        return self


class LegacyReportTaskResult(SchemaModel):
    task_id: str = Field(min_length=1)
    status: Literal["completed", "unsupported", "failed"]
    answer_fragment: str = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)
