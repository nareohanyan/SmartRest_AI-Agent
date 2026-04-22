from __future__ import annotations

from app.agent.parser_numbers import normalize_number_words


def test_normalize_number_words_converts_armenian_words_to_digits() -> None:
    assert normalize_number_words("նախորդ երկու ամսվա մեջ") == "նախորդ 2 ամսվա մեջ"


def test_normalize_number_words_converts_english_words_to_digits() -> None:
    assert normalize_number_words("show top five menu items") == "show top 5 menu items"


def test_normalize_number_words_converts_russian_words_to_digits() -> None:
    assert normalize_number_words("за последние два месяца") == "за последние 2 месяца"
