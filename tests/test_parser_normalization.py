from __future__ import annotations

from app.agent.parser_normalization import (
    build_semantic_base_tokens,
    normalize_smalltalk_text,
    normalize_text,
    semantic_tokens,
)


def test_normalize_text_collapses_case_and_punctuation() -> None:
    normalized = normalize_text("  Նախորդ ամսվա եկամուտս ինչքա՞նա կազմել։  ")

    assert normalized == "նախորդ ամսվա եկամուտս ինչքա նա կազմել"


def test_normalize_smalltalk_text_strips_trailing_punctuation() -> None:
    normalized = normalize_smalltalk_text("Բարև!!!")

    assert normalized == "բարև"


def test_semantic_tokens_strip_safe_armenian_suffixes_only_for_known_terms() -> None:
    base_tokens = build_semantic_base_tokens({"եկամուտ", "վաճառք", "sales"})

    tokens = semantic_tokens("նախորդ ամսվա եկամուտս", base_tokens=base_tokens)

    assert "եկամուտս" in tokens
    assert "եկամուտ" in tokens


def test_semantic_tokens_do_not_strip_unknown_armenian_terms_aggressively() -> None:
    base_tokens = build_semantic_base_tokens({"եկամուտ", "վաճառք", "sales"})

    tokens = semantic_tokens("պատահականս", base_tokens=base_tokens)

    assert "պատահականս" in tokens
    assert "պատահական" not in tokens


def test_normalize_text_applies_known_high_signal_business_term_corrections() -> None:
    normalized = normalize_text("ամենաշատ վաճարված ապրանքը")

    assert normalized == "ամենաշատ վաճառված ապրանքը"
