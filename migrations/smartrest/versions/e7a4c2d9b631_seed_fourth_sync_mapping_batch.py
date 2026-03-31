"""seed fourth sync mapping batch

Revision ID: e7a4c2d9b631
Revises: 9d2a6f8b1c55
Create Date: 2026-03-31 01:20:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a4c2d9b631"
down_revision: str | Sequence[str] | None = "9d2a6f8b1c55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE_MAPPINGS = (
    {
        "src_table": "st_material_category_language",
        "dst_table": "material_category_language",
        "src_pk": "id",
        "comment": "Fourth sync batch mapping for material category languages.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
            ("language_id", "language_id", None),
            ("title", "title", None),
            ("material_category_id", "material_category_id", None),
        ),
    },
    {
        "src_table": "st_material_language",
        "dst_table": "material_language",
        "src_pk": "id",
        "comment": "Fourth sync batch mapping for material languages.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
            ("language_id", "language_id", None),
            ("title", "title", None),
            ("material_id", "material_id", None),
        ),
    },
    {
        "src_table": "st_store_language",
        "dst_table": "store_language",
        "src_pk": "id",
        "comment": "Fourth sync batch mapping for store languages.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
            ("language_id", "language_id", None),
            ("title", "title", None),
            ("store_id", "store_id", None),
        ),
    },
    {
        "src_table": "st_unit",
        "dst_table": "units",
        "src_pk": "id",
        "comment": "Fourth sync batch mapping for units.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
        ),
    },
    {
        "src_table": "st_unit_language",
        "dst_table": "unit_language",
        "src_pk": "id",
        "comment": "Fourth sync batch mapping for unit languages.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
            ("language_id", "language_id", None),
            ("title", "title", None),
            ("unit_id", "unit_id", None),
        ),
    },
    {
        "src_table": "fifo_history",
        "dst_table": "fifo_history",
        "src_pk": "id",
        "comment": "Fourth sync batch mapping for FIFO history.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
            ("state_id", "state_id", None),
            ("quantity_in", "quantity_in", None),
            ("quantity_out", "quantity_out", None),
            ("document_id", "document_id", None),
            ("document_content_id", "document_content_id", None),
            ("order_id", "order_id", None),
            ("order_content_id", "order_content_id", None),
            ("branch_id", "branch_id", None),
            ("changed", "changed", None),
        ),
    },
    {
        "src_table": "fifo_state",
        "dst_table": "fifo_state",
        "src_pk": "id",
        "comment": "Fourth sync batch mapping for FIFO state.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
            ("store_id", "store_id", None),
            ("item_id", "item_id", None),
            ("price", "price", None),
            ("branch_id", "branch_id", None),
        ),
    },
    {
        "src_table": "fiscal_receipt",
        "dst_table": "fiscal_receipt",
        "src_pk": "id",
        "comment": "Fourth sync batch mapping for fiscal receipts.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
            ("order_id", "order_id", None),
            ("report_type", "report_type", None),
            ("report_start", "report_start", None),
            ("report_end", "report_end", None),
            ("status", "status", None),
            ("order_prepayment", "order_prepayment", None),
            ("order_history_id", "order_history_id", None),
            ("return_receipt_id", "return_receipt_id", None),
        ),
    },
    {
        "src_table": "fiscal_receipt_history",
        "dst_table": "fiscal_receipt_history",
        "src_pk": "id",
        "comment": "Fourth sync batch mapping for fiscal receipt history.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
            ("receipt_id", "receipt_id", None),
            ("rseq", "rseq", None),
            ("crn", "crn", None),
            ("sn", "sn", None),
            ("tin", "tin", None),
            ("time", "time", None),
            ("fiscal", "fiscal", None),
            ("total", "total", None),
            ("change", "change", None),
        ),
    },
    {
        "src_table": "branch",
        "dst_table": "branches",
        "src_pk": "id",
        "comment": "Fourth sync batch mapping for branches.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
        ),
    },
    {
        "src_table": "menu_items",
        "dst_table": "menu_items",
        "src_pk": "id",
        "comment": "Fourth sync batch mapping for menu items, including freezed -> frozen rename.",
        "columns": (
            ("id", "id", None),
            ("profile", "profile", None),
            ("group", "group", None),
            ("name", "name", None),
            ("name_ru", "name_ru", None),
            ("name_en", "name_en", None),
            ("price", "price", None),
            ("check_place", "check_place", None),
            ("description", "description", None),
            ("barcode", "barcode", None),
            ("freezed", "frozen", None),
            ("deleted", "deleted", None),
            ("type", "type", None),
            ("suspended", "suspended", None),
            ("suspend_date", "suspend_date", None),
            ("activate_date", "activate_date", None),
            ("branch_id", "branch_id", None),
            ("hdm_name", "hdm_name", None),
            ("code", "code", None),
        ),
    },
    {
        "src_table": "menu_group",
        "dst_table": "menu_group",
        "src_pk": "id",
        "comment": "Fourth sync batch mapping for menu groups.",
        "columns": (
            ("id", "id", None),
            ("profile", "profile", None),
            ("place", "place", None),
            ("title", "title", None),
            ("title_ru", "title_ru", None),
            ("title_en", "title_en", None),
            ("deleted", "deleted", None),
            ("branch_id", "branch_id", None),
        ),
    },
    {
        "src_table": "menu_place",
        "dst_table": "menu_place",
        "src_pk": "id",
        "comment": "Fourth sync batch mapping for menu places.",
        "columns": (
            ("id", "id", None),
            ("profile", "profile", None),
            ("title", "title", None),
            ("title_ru", "title_ru", None),
            ("title_en", "title_en", None),
            ("store", "store", None),
            ("deleted", "deleted", None),
            ("branch_id", "branch_id", None),
        ),
    },
    {
        "src_table": "moved_items",
        "dst_table": "moved_items",
        "src_pk": "id",
        "comment": "Fourth sync batch mapping for moved items.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
            ("order_id", "order_id", None),
            ("new_order_id", "new_order_id", None),
            ("order_uniq_id", "order_uniq_id", None),
            ("new_order_uniq_id", "new_order_uniq_id", None),
            ("content_id", "content_id", None),
            ("menu_item_id", "menu_item_id", None),
            ("menu_item_count", "menu_item_count", None),
            ("table_id", "table_id", None),
            ("branch_id", "branch_id", None),
        ),
    },
    {
        "src_table": "menu_item_content",
        "dst_table": "menu_item_content",
        "src_pk": "id",
        "comment": "Fourth sync batch mapping for menu item content.",
        "columns": (
            ("id", "id", None),
            ("profile", "profile", None),
            ("menu_item", "menu_item", None),
            ("store_item", "store_item", None),
            ("store_item_count", "store_item_count", None),
            ("package_id", "package_id", None),
            ("visibility", "visibility", None),
            ("store", "store", None),
            ("suspended", "suspended", None),
            ("branch_id", "branch_id", None),
        ),
    },
    {
        "src_table": "order_payment_history",
        "dst_table": "order_payment_history",
        "src_pk": "id",
        "comment": "Fourth sync batch mapping for order payment history.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
            ("order_id", "order_id", None),
            ("total_price", "total_price", None),
            ("payed", "payed", None),
            ("cashbox_id", "cashbox_id", None),
            ("card_id", "card_id", None),
            ("cashbox_history_id", "cashbox_history_id", None),
        ),
    },
    {
        "src_table": "translate",
        "dst_table": "translate",
        "src_pk": "Id",
        "comment": "Fourth sync batch mapping for translations.",
        "columns": (
            ("Id", "Id", None),
            ("string", "string", None),
            ("en", "en", None),
            ("hy", "hy", None),
            ("ru", "ru", None),
        ),
    },
)


def upgrade() -> None:
    bind = op.get_bind()
    insert_table_map = sa.text(
        """
        INSERT INTO migrations.table_map (src_table, dst_table, src_pk, comment, is_active)
        VALUES (:src_table, :dst_table, :src_pk, :comment, true)
        RETURNING id
        """
    )
    insert_column_map = sa.text(
        """
        INSERT INTO migrations.column_map (table_map_id, src_column, dst_column, transform)
        VALUES (:table_map_id, :src_column, :dst_column, :transform)
        """
    )

    for mapping in _TABLE_MAPPINGS:
        table_map_id = bind.execute(
            insert_table_map,
            {
                "src_table": mapping["src_table"],
                "dst_table": mapping["dst_table"],
                "src_pk": mapping["src_pk"],
                "comment": mapping["comment"],
            },
        ).scalar_one()
        bind.execute(
            insert_column_map,
            [
                {
                    "table_map_id": table_map_id,
                    "src_column": src_column,
                    "dst_column": dst_column,
                    "transform": transform,
                }
                for src_column, dst_column, transform in mapping["columns"]
            ],
        )


def downgrade() -> None:
    bind = op.get_bind()
    src_tables = tuple(mapping["src_table"] for mapping in _TABLE_MAPPINGS)
    dst_tables = tuple(mapping["dst_table"] for mapping in _TABLE_MAPPINGS)

    bind.execute(
        sa.text(
            """
            DELETE FROM migrations.column_map
            WHERE table_map_id IN (
                SELECT id
                FROM migrations.table_map
                WHERE src_table IN :src_tables
                  AND dst_table IN :dst_tables
            )
            """
        ).bindparams(
            sa.bindparam("src_tables", expanding=True),
            sa.bindparam("dst_tables", expanding=True),
        ),
        {"src_tables": src_tables, "dst_tables": dst_tables},
    )
    bind.execute(
        sa.text(
            """
            DELETE FROM migrations.table_map
            WHERE src_table IN :src_tables
              AND dst_table IN :dst_tables
            """
        ).bindparams(
            sa.bindparam("src_tables", expanding=True),
            sa.bindparam("dst_tables", expanding=True),
        ),
        {"src_tables": src_tables, "dst_tables": dst_tables},
    )
