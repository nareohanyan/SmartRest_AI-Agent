"""Deterministic calculation selection policy for C3 graph integration."""

from __future__ import annotations

from decimal import Decimal

from app.schemas.agent import IntentType
from app.schemas.calculations import (
    CalculationSpec,
    DeltaCalculationSpec,
    PercentChangeCalculationSpec,
    PerDayRateCalculationSpec,
    SharePercentCalculationSpec,
)
from app.schemas.reports import ReportType


def _append_period_comparison_calculations(
    calculations: list[CalculationSpec],
    *,
    metric_key: str,
    base_metrics: dict[str, Decimal],
) -> None:
    previous_key = f"{metric_key}_previous"
    if metric_key not in base_metrics or previous_key not in base_metrics:
        return

    calculations.append(
        DeltaCalculationSpec(
            output_key=f"{metric_key}_delta",
            current_key=metric_key,
            previous_key=previous_key,
        )
    )
    calculations.append(
        PercentChangeCalculationSpec(
            output_key=f"{metric_key}_percent_change",
            current_key=metric_key,
            previous_key=previous_key,
        )
    )


def select_calculation_specs(
    report_id: ReportType,
    intent: IntentType | None,
    base_metrics: dict[str, Decimal],
) -> list[CalculationSpec]:
    """Select deterministic formula specs by report semantics and available metrics."""
    del intent
    calculations: list[CalculationSpec] = []

    if report_id is ReportType.SALES_TOTAL and "sales_total" in base_metrics:
        if "day_count" in base_metrics:
            calculations.append(
                PerDayRateCalculationSpec(
                    output_key="sales_total_per_day",
                    metric_key="sales_total",
                    day_count_key="day_count",
                )
            )
        _append_period_comparison_calculations(
            calculations,
            metric_key="sales_total",
            base_metrics=base_metrics,
        )
        return calculations

    if report_id is ReportType.ORDER_COUNT and "order_count" in base_metrics:
        if "day_count" in base_metrics:
            calculations.append(
                PerDayRateCalculationSpec(
                    output_key="order_count_per_day",
                    metric_key="order_count",
                    day_count_key="day_count",
                )
            )
        _append_period_comparison_calculations(
            calculations,
            metric_key="order_count",
            base_metrics=base_metrics,
        )
        return calculations

    if report_id is ReportType.AVERAGE_CHECK and "average_check" in base_metrics:
        _append_period_comparison_calculations(
            calculations,
            metric_key="average_check",
            base_metrics=base_metrics,
        )
        return calculations

    if report_id is ReportType.SALES_BY_SOURCE and "sales_total" in base_metrics:
        source_keys = sorted(
            key
            for key in base_metrics
            if key.startswith("source_") and key.endswith("_sales")
        )
        for source_key in source_keys:
            source_name = source_key.removeprefix("source_").removesuffix("_sales")
            calculations.append(
                SharePercentCalculationSpec(
                    output_key=f"share_percent_{source_name}",
                    part_key=source_key,
                    total_key="sales_total",
                )
            )

    return calculations
