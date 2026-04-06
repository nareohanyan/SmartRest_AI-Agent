from __future__ import annotations

import sqlalchemy as sa

from app.sync.mapped_table_sync import (
    ColumnMapping,
    TableMapping,
    _filter_mappings,
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

