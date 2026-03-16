"""Unit tests for deterministic calculation selection policy (C3)."""

from __future__ import annotations

from decimal import Decimal

from app.agent.calc_policy import select_calculation_specs
from app.schemas.agent import IntentType
from app.schemas.calculations import (
    DeltaCalculationSpec,
    PercentChangeCalculationSpec,
    PerDayRateCalculationSpec,
    SharePercentCalculationSpec,
)
from app.schemas.reports import ReportType


def test_select_calc_specs_for_sales_total_adds_per_day_rate() -> None:
    calculations = select_calculation_specs(
        ReportType.SALES_TOTAL,
        IntentType.GET_KPI,
        {
            "sales_total": Decimal("12345.67"),
            "day_count": Decimal("7"),
        },
    )

    assert len(calculations) == 1
    assert isinstance(calculations[0], PerDayRateCalculationSpec)
    assert calculations[0].output_key == "sales_total_per_day"


def test_select_calc_specs_for_sales_total_adds_comparison_when_previous_exists() -> None:
    calculations = select_calculation_specs(
        ReportType.SALES_TOTAL,
        IntentType.GET_KPI,
        {
            "sales_total": Decimal("12345.67"),
            "sales_total_previous": Decimal("10000.00"),
            "day_count": Decimal("7"),
        },
    )

    assert len(calculations) == 3
    assert isinstance(calculations[0], PerDayRateCalculationSpec)
    assert isinstance(calculations[1], DeltaCalculationSpec)
    assert isinstance(calculations[2], PercentChangeCalculationSpec)


def test_select_calc_specs_for_sales_by_source_adds_share_percent_per_source() -> None:
    calculations = select_calculation_specs(
        ReportType.SALES_BY_SOURCE,
        IntentType.BREAKDOWN_KPI,
        {
            "day_count": Decimal("7"),
            "sales_total": Decimal("12345.67"),
            "source_wolt_sales": Decimal("2200.00"),
            "source_glovo_sales": Decimal("4100.00"),
            "source_in_store_sales": Decimal("5200.00"),
        },
    )

    assert [spec.output_key for spec in calculations] == [
        "share_percent_glovo",
        "share_percent_in_store",
        "share_percent_wolt",
    ]
    assert all(isinstance(spec, SharePercentCalculationSpec) for spec in calculations)


def test_select_calc_specs_for_average_check_without_history_returns_empty() -> None:
    calculations = select_calculation_specs(
        ReportType.AVERAGE_CHECK,
        IntentType.GET_KPI,
        {
            "average_check": Decimal("35.78"),
            "day_count": Decimal("7"),
        },
    )

    assert calculations == []
