"""Data-driven planner lexicon loader."""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from functools import lru_cache
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PlannerLexicon:
    pure_smalltalk_phrases: set[str]
    greeting_tokens: set[str]
    smalltalk_support_tokens: set[str]
    metric_terms: set[str]
    high_priority_business_terms: set[str]
    operation_terms: set[str]
    dimension_terms: set[str]
    relative_today_terms: set[str]
    relative_yesterday_terms: set[str]
    relative_last_week_terms: set[str]
    relative_this_month_terms: set[str]
    relative_past_30_days_terms: set[str]
    average_metric_terms: set[str]
    order_metric_terms: set[str]
    sales_metric_terms: set[str]
    breakdown_terms: set[str]
    ranking_top_terms: set[str]
    ranking_bottom_terms: set[str]
    trend_terms: set[str]
    comparison_terms: set[str]


def _normalize_term(term: str) -> str:
    return " ".join(term.strip().lower().replace("’", "'").split())


def _load_term_set(payload: dict[str, Any], key: str) -> set[str]:
    raw_terms = payload.get(key)
    if not isinstance(raw_terms, list):
        raise ValueError(f"Planner lexicon key `{key}` must be a list.")

    normalized_terms: set[str] = set()
    for index, raw_term in enumerate(raw_terms):
        if not isinstance(raw_term, str):
            raise ValueError(
                f"Planner lexicon key `{key}` contains non-string term at index {index}."
            )
        normalized = _normalize_term(raw_term)
        if normalized:
            normalized_terms.add(normalized)
    return normalized_terms


def load_planner_lexicon(path: Path) -> PlannerLexicon:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Planner lexicon file must contain a JSON object.")

    term_sets: dict[str, set[str]] = {}
    for field in fields(PlannerLexicon):
        term_sets[field.name] = _load_term_set(payload, field.name)
    return PlannerLexicon(**term_sets)


@lru_cache(maxsize=1)
def get_planner_lexicon() -> PlannerLexicon:
    lexicon_path = Path(__file__).with_name("planner_lexicon.json")
    return load_planner_lexicon(lexicon_path)
