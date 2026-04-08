from __future__ import annotations

from datetime import date, datetime, timezone

import sqlalchemy as sa

from app.sync.mapped_table_sync import (
    ColumnMapping,
    TableMapping,
    _classify_skippable_row_error,
    _filter_mappings,
    _is_foreign_key_violation,
    _is_invalid_boolean_value_error,
    _normalize_payload_for_target,
    _order_mappings_by_fk,
    _safe_int,
)


def _mapping(src: str, dst: str) -> TableMapping:
    return TableMapping(
        id=1,
        src_table=src,
        dst_table=dst,
        src_pk="id",
        columns=(ColumnMapping(src_column="id", dst_column="id"),),
    )


def test_filter_mappings_include_exclude() -> None:
    mappings = (
        _mapping("profiles", "profiles"),
        _mapping("profiles_users", "users"),
        _mapping("profiles_room_table_order", "orders"),
    )

    filtered = _filter_mappings(
        mappings=mappings,
        include_tables=("users",),
        exclude_tables=(),
    )
    assert [item.dst_table for item in filtered] == ["users"]

    filtered = _filter_mappings(
        mappings=mappings,
        include_tables=(),
        exclude_tables=("orders",),
    )
    assert [item.dst_table for item in filtered] == ["profiles", "users"]


def test_order_mappings_by_fk_parent_first() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    metadata = sa.MetaData()
    sa.Table("profiles", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("profile_id", sa.Integer, sa.ForeignKey("profiles.id")),
    )
    sa.Table(
        "orders",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("profile_id", sa.Integer, sa.ForeignKey("profiles.id")),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id")),
    )
    metadata.create_all(engine)

    mappings = (
        _mapping("profiles_room_table_order", "orders"),
        _mapping("profiles_users", "users"),
        _mapping("profiles", "profiles"),
    )
    ordered = _order_mappings_by_fk(mappings=mappings, target_engine=engine)
    assert [item.dst_table for item in ordered] == ["profiles", "users", "orders"]


def test_safe_int_handles_common_inputs() -> None:
    assert _safe_int(42) == 42
    assert _safe_int("42") == 42
    assert _safe_int(" 42 ") == 42
    assert _safe_int("x") is None
    assert _safe_int(None) is None


def test_normalize_payload_timestamptz_and_empty_string() -> None:
    metadata = sa.MetaData()
    table = sa.Table(
        "events",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    payload = _normalize_payload_for_target(
        raw_payload={"id": 1, "created_at": 1683819710, "ended_at": ""},
        target_table=table,
    )
    assert payload["id"] == 1
    assert payload["created_at"] == datetime(2023, 5, 11, 15, 41, 50, tzinfo=timezone.utc)
    assert payload["ended_at"] is None


def test_normalize_payload_timestamptz_zero_epoch_to_null() -> None:
    metadata = sa.MetaData()
    table = sa.Table(
        "events",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    payload = _normalize_payload_for_target(
        raw_payload={"id": 1, "created_at": 0, "ended_at": "0"},
        target_table=table,
    )
    assert payload["created_at"] is None
    assert payload["ended_at"] is None


def test_normalize_payload_boolean_json_and_date() -> None:
    metadata = sa.MetaData()
    table = sa.Table(
        "sample",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("enabled", sa.Boolean, nullable=True),
        sa.Column("meta", sa.JSON, nullable=True),
        sa.Column("event_day", sa.Date, nullable=True),
    )
    payload = _normalize_payload_for_target(
        raw_payload={
            "id": 7,
            "enabled": "1",
            "meta": '{"ok": true}',
            "event_day": "2026-04-06",
        },
        target_table=table,
    )
    assert payload["id"] == 7
    assert payload["enabled"] is True
    assert payload["meta"] == {"ok": True}
    assert payload["event_day"] == date(2026, 4, 6)


def test_normalize_payload_date_zero_epoch_to_null() -> None:
    metadata = sa.MetaData()
    table = sa.Table(
        "sample",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("event_day", sa.Date, nullable=True),
    )
    payload = _normalize_payload_for_target(
        raw_payload={"id": 7, "event_day": 0},
        target_table=table,
    )
    assert payload["event_day"] is None


def test_normalize_payload_nullable_fk_zero_to_null() -> None:
    metadata = sa.MetaData()
    parent = sa.Table(
        "menu_items",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
    )
    table = sa.Table(
        "history",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("menu_item_id", sa.Integer, sa.ForeignKey(parent.c.id), nullable=True),
    )
    payload = _normalize_payload_for_target(
        raw_payload={"id": 1, "menu_item_id": 0},
        target_table=table,
    )
    assert payload["menu_item_id"] is None

    payload = _normalize_payload_for_target(
        raw_payload={"id": 2, "menu_item_id": "0"},
        target_table=table,
    )
    assert payload["menu_item_id"] is None


class _FakeDbError(Exception):
    def __init__(self, *, sqlstate: str | None = None, orig: object | None = None) -> None:
        super().__init__("fake db error")
        self.sqlstate = sqlstate
        self.orig = orig


class _ForeignKeyViolation:
    pass


def test_is_foreign_key_violation_detects_sqlstate() -> None:
    exc = _FakeDbError(sqlstate="23503")
    assert _is_foreign_key_violation(exc) is True


def test_is_foreign_key_violation_detects_orig_class_name() -> None:
    exc = _FakeDbError(orig=_ForeignKeyViolation())
    assert _is_foreign_key_violation(exc) is True


def test_is_foreign_key_violation_ignores_other_sqlstate() -> None:
    exc = _FakeDbError(sqlstate="23505")
    assert _is_foreign_key_violation(exc) is False


def test_is_invalid_boolean_value_error_detects_message() -> None:
    exc = ValueError("Value 2 is not None, True, or False")
    assert _is_invalid_boolean_value_error(exc) is True


def test_classify_skippable_row_error_for_boolean() -> None:
    exc = ValueError("Value 2 is not None, True, or False")
    assert _classify_skippable_row_error(exc) == "mapped_table_invalid_boolean"
