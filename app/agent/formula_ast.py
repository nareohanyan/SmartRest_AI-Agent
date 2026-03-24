from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal, TypeAlias

from pydantic import Field

from app.schemas.base import SchemaModel


class FormulaAstKind(str, Enum):
    RATIO = "ratio"
    SUM = "sum"
    DIFFERENCE = "difference"
    MULTIPLY = "multiply"


class FormulaWarningCode(str, Enum):
    MISSING_OPERAND = "missing_operand"
    DIVISION_BY_ZERO = "division_by_zero"


class RatioFormulaAst(SchemaModel):
    kind: Literal["ratio"] = "ratio"
    numerator_metric_id: str = Field(min_length=1)
    denominator_metric_id: str = Field(min_length=1)


class SumFormulaAst(SchemaModel):
    kind: Literal["sum"] = "sum"
    metric_ids: list[str] = Field(min_length=2)


class DifferenceFormulaAst(SchemaModel):
    kind: Literal["difference"] = "difference"
    minuend_metric_id: str = Field(min_length=1)
    subtrahend_metric_id: str = Field(min_length=1)


class MultiplyFormulaAst(SchemaModel):
    kind: Literal["multiply"] = "multiply"
    left_metric_id: str = Field(min_length=1)
    right_metric_id: str = Field(min_length=1)


FormulaAst: TypeAlias = Annotated[
    RatioFormulaAst | SumFormulaAst | DifferenceFormulaAst | MultiplyFormulaAst,
    Field(discriminator="kind"),
]


def formula_metric_dependencies(ast: FormulaAst) -> set[str]:
    if isinstance(ast, RatioFormulaAst):
        return {ast.numerator_metric_id, ast.denominator_metric_id}
    if isinstance(ast, SumFormulaAst):
        return set(ast.metric_ids)
    if isinstance(ast, DifferenceFormulaAst):
        return {ast.minuend_metric_id, ast.subtrahend_metric_id}
    if isinstance(ast, MultiplyFormulaAst):
        return {ast.left_metric_id, ast.right_metric_id}
    raise ValueError(f"Unsupported formula ast kind: {ast}")


def validate_formula_ast(
    *,
    ast: FormulaAst,
    known_metric_ids: set[str],
) -> None:
    unknown_ids = sorted(formula_metric_dependencies(ast).difference(known_metric_ids))
    if unknown_ids:
        joined = ", ".join(unknown_ids)
        raise ValueError(f"Formula references unknown metric ids: {joined}")


def evaluate_formula_ast(
    *,
    ast: FormulaAst,
    base_metrics: dict[str, Decimal],
) -> tuple[Decimal | None, list[FormulaWarningCode]]:
    warnings: list[FormulaWarningCode] = []

    def _get_value(metric_id: str) -> Decimal | None:
        value = base_metrics.get(metric_id)
        if value is None:
            if FormulaWarningCode.MISSING_OPERAND not in warnings:
                warnings.append(FormulaWarningCode.MISSING_OPERAND)
            return None
        return value

    if isinstance(ast, RatioFormulaAst):
        numerator = _get_value(ast.numerator_metric_id)
        denominator = _get_value(ast.denominator_metric_id)
        if numerator is None or denominator is None:
            return None, warnings
        if denominator == 0:
            warnings.append(FormulaWarningCode.DIVISION_BY_ZERO)
            return None, warnings
        return numerator / denominator, warnings

    if isinstance(ast, SumFormulaAst):
        values = [_get_value(metric_id) for metric_id in ast.metric_ids]
        if any(value is None for value in values):
            return None, warnings
        return sum((value for value in values if value is not None), Decimal("0")), warnings

    if isinstance(ast, DifferenceFormulaAst):
        minuend = _get_value(ast.minuend_metric_id)
        subtrahend = _get_value(ast.subtrahend_metric_id)
        if minuend is None or subtrahend is None:
            return None, warnings
        return minuend - subtrahend, warnings

    if isinstance(ast, MultiplyFormulaAst):
        left = _get_value(ast.left_metric_id)
        right = _get_value(ast.right_metric_id)
        if left is None or right is None:
            return None, warnings
        return left * right, warnings

    raise ValueError(f"Unsupported formula ast kind: {ast}")
