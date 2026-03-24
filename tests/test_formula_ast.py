from __future__ import annotations

from decimal import Decimal

import pytest

from app.agent.formula_ast import (
    FormulaWarningCode,
    RatioFormulaAst,
    SumFormulaAst,
    evaluate_formula_ast,
    validate_formula_ast,
)


def test_evaluate_formula_ast_ratio_success() -> None:
    value, warnings = evaluate_formula_ast(
        ast=RatioFormulaAst(
            numerator_metric_id="sales_total",
            denominator_metric_id="completed_order_count",
        ),
        base_metrics={
            "sales_total": Decimal("250"),
            "completed_order_count": Decimal("10"),
        },
    )

    assert value == Decimal("25")
    assert warnings == []


def test_evaluate_formula_ast_ratio_division_by_zero_warning() -> None:
    value, warnings = evaluate_formula_ast(
        ast=RatioFormulaAst(
            numerator_metric_id="sales_total",
            denominator_metric_id="completed_order_count",
        ),
        base_metrics={
            "sales_total": Decimal("250"),
            "completed_order_count": Decimal("0"),
        },
    )

    assert value is None
    assert warnings == [FormulaWarningCode.DIVISION_BY_ZERO]


def test_validate_formula_ast_rejects_unknown_metric_ids() -> None:
    with pytest.raises(ValueError, match="unknown metric ids"):
        validate_formula_ast(
            ast=SumFormulaAst(metric_ids=["sales_total", "unknown_metric"]),
            known_metric_ids={"sales_total", "order_count"},
        )

