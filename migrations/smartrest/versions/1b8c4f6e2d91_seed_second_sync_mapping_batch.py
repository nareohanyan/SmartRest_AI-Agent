"""seed second sync mapping batch

Revision ID: 1b8c4f6e2d91
Revises: 6b1d0c1f0b4a
Create Date: 2026-03-31 00:30:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1b8c4f6e2d91"
down_revision: str | Sequence[str] | None = "6b1d0c1f0b4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE_MAPPINGS = (
    {
        "src_table": "profiles_room_table_order",
        "dst_table": "orders",
        "src_pk": "id",
        "comment": "Second sync batch mapping for orders.",
        "columns": (
            ("id", "id", None),
            ("profile_id", "profile_id", None),
            ("profile_order_uniq_id", "profile_order_uniq_id", None),
            ("room_table_id", "room_table_id", None),
            ("profile_staff_id", "profile_staff_id", None),
            ("room_table_status", "room_table_status", None),
            ("order_create_date", "order_create_date", None),
            ("delivery_id", "delivery_id", None),
            ("delivery_date", "delivery_date", None),
            ("client_id", "client_id", None),
            ("table_commissions_type", "table_commissions_type", None),
            ("table_commissions_value", "table_commissions_value", None),
            ("total_price", "total_price", None),
            ("sale", "sale", None),
            ("payed", "payed", None),
            ("payment_status", "payment_status", None),
            ("json", "json", None),
            ("tip", "tip", None),
            ("deposit", "deposit", None),
            ("branch_id", "branch_id", None),
            ("final_total", "final_total", None),
            ("time_percent", "time_percent", None),
            ("fix_percent", "fix_percent", None),
            ("clients_count", "clients_count", None),
            ("status_id", "status_id", None),
            ("terminate_date", "terminate_date", None),
            ("type_id", "type_id", None),
            ("delivery_price", "delivery_price", None),
            ("commission_total", "commission_total", None),
            ("cashbox_id", "cashbox_id", None),
            ("hourly_pay_without_product", "hourly_pay_without_product", None),
            ("is_delivery", "is_delivery", None),
            ("discounted_amount", "discounted_amount", None),
            ("sale_description", "sale_description", None),
            ("order_type", "order_type", None),
        ),
    },
    {
        "src_table": "profiles_room_table_order_content",
        "dst_table": "order_contents",
        "src_pk": "id",
        "comment": "Second sync batch mapping for order contents.",
        "columns": (
            ("id", "id", None),
            ("profile_id", "profile_id", None),
            ("room_table_order_id", "room_table_order_id", None),
            ("subtable_id", "subtable_id", None),
            ("suborder_id", "suborder_id", None),
            ("profile_menu_item_id", "profile_menu_item_id", None),
            ("profile_menu_item_count", "profile_menu_item_count", None),
            ("cost_price", "cost_price", None),
            ("item_price", "item_price", None),
            ("create_date", "create_date", None),
            ("json", "json", None),
            ("cashback_value", "cashback_value", None),
            ("done", "done", None),
            ("product_sale", "product_sale", None),
            ("branch_id", "branch_id", None),
            ("staff_id", "staff_id", None),
            ("order_in", "order_in", None),
            ("e_marks", "e_marks", None),
        ),
    },
    {
        "src_table": "profiles_room_table_order_content_removed",
        "dst_table": "order_content_removed",
        "src_pk": "id",
        "comment": "Second sync batch mapping for removed order contents.",
        "columns": (
            ("id", "id", None),
            ("profile_id", "profile_id", None),
            ("room_table_order_id", "room_table_order_id", None),
            ("suborder_id", "suborder_id", None),
            ("profile_menu_item_id", "profile_menu_item_id", None),
            ("profile_menu_item_count", "profile_menu_item_count", None),
            ("create_date", "create_date", None),
            ("remove_date", "remove_date", None),
            ("json", "json", None),
            ("branch_id", "branch_id", None),
            ("add_date", "add_date", None),
        ),
    },
    {
        "src_table": "profiles_room_table_order_package_components",
        "dst_table": "profiles_room_table_order_package_components",
        "src_pk": "id",
        "comment": "Second sync batch mapping for order package components.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
            ("room_table_order_content_id", "room_table_order_content_id", None),
            ("profile_menu_item_id", "profile_menu_item_id", None),
            ("profile_menu_item_count", "profile_menu_item_count", None),
            ("cost_price", "cost_price", None),
            ("item_price", "item_price", None),
            ("json", "json", None),
            ("branch_id", "branch_id", None),
        ),
    },
    {
        "src_table": "profiles_clients",
        "dst_table": "clients",
        "src_pk": "id",
        "comment": "Second sync batch mapping for clients.",
        "columns": (
            ("id", "id", None),
            ("profile_id", "profile_id", None),
            ("name", "name", None),
            ("address", "address", None),
            ("phone", "phone", None),
            ("deleted", "deleted", None),
            ("email", "email", None),
            ("sex", "sex", None),
            ("company", "company", None),
            ("remote_id", "remote_id", None),
            ("identification_document", "identification_document", None),
        ),
    },
    {
        "src_table": "profiles_clients_cards_history",
        "dst_table": "clients_cards_history",
        "src_pk": "id",
        "comment": "Second sync batch mapping for client card history.",
        "columns": (
            ("id", "id", None),
            ("profile_id", "profile_id", None),
            ("client_id", "client_id", None),
            ("card_code", "card_code", None),
            ("value", "value", None),
            ("balance", "balance", None),
            ("create_date", "create_date", None),
            ("menu_item_id", "menu_item_id", None),
            ("menu_item_count", "menu_item_count", None),
            ("menu_item_balance", "menu_item_balance", None),
            ("menu_item_price", "menu_item_price", None),
            ("room_table_order_id", "room_table_order_id", None),
            ("branch_id", "branch_id", None),
            ("bonus_id", "bonus_id", None),
            ("bonus_name", "bonus_name", None),
        ),
    },
    {
        "src_table": "st_store",
        "dst_table": "stores",
        "src_pk": "id",
        "comment": "Second sync batch mapping for stores. Source created_at and updated_at are intentionally ignored.",
        "columns": (
            ("id", "id", None),
            ("branch_id", "branch_id", None),
            ("profile_id", "profile_id", None),
            ("archived", "archived", None),
            ("deleted", "deleted", None),
            ("modifier", "modifier", None),
        ),
    },
    {
        "src_table": "st_balance_history",
        "dst_table": "balance_history",
        "src_pk": "id",
        "comment": "Second sync batch mapping for stock balance history.",
        "columns": (
            ("id", "id", None),
            ("original_create_date", "original_create_date", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
            ("store_id", "store_id", None),
            ("material_id", "material_id", None),
            ("document_id", "document_id", None),
            ("type_id", "type_id", None),
            ("branch_id", "branch_id", None),
            ("quantity_in", "quantity_in", None),
            ("quantity_out", "quantity_out", None),
            ("balance", "balance", None),
            ("order_id", "order_id", None),
            ("order_content_id", "order_content_id", None),
            ("price", "price", None),
            ("document_content_id", "document_content_id", None),
            ("useful_weight_quantity", "useful_weight_quantity", None),
            ("fix_price", "fix_price", None),
            ("fix_balance", "fix_balance", None),
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
