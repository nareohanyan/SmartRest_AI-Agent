from __future__ import annotations

import sqlalchemy as sa

from app.smartrest.models import (
    MaterialCategoryLanguage,
    MaterialLanguage,
    MeasurementLanguage,
    StoreLanguage,
    Translate,
)


def test_translation_tables_store_language_codes_as_strings() -> None:
    assert isinstance(MaterialCategoryLanguage.__table__.c.language_id.type, sa.String)
    assert isinstance(MaterialLanguage.__table__.c.language_id.type, sa.String)
    assert isinstance(StoreLanguage.__table__.c.language_id.type, sa.String)
    assert isinstance(MeasurementLanguage.__table__.c.language_id.type, sa.String)


def test_translate_string_allows_source_width() -> None:
    assert isinstance(Translate.__table__.c.string.type, sa.String)
    assert Translate.__table__.c.string.type.length == 1000
