from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.planner_lexicon import get_planner_lexicon, load_planner_lexicon


def test_default_lexicon_loads_with_expected_terms() -> None:
    lexicon = get_planner_lexicon()

    assert "բարև" in lexicon.pure_smalltalk_phrases
    assert "привет" in lexicon.greeting_tokens
    assert "сегодня" in lexicon.relative_today_terms
    assert "compare" in lexicon.comparison_terms
    assert "աղբյուրով" in lexicon.breakdown_terms


def test_load_planner_lexicon_rejects_invalid_shape(tmp_path: Path) -> None:
    bad_payload = tmp_path / "planner_lexicon_bad.json"
    bad_payload.write_text('{"pure_smalltalk_phrases": "hello"}', encoding="utf-8")

    with pytest.raises(ValueError):
        load_planner_lexicon(bad_payload)
