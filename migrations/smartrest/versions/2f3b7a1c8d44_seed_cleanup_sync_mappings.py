"""seed cleanup sync mappings

Revision ID: 2f3b7a1c8d44
Revises: e7a4c2d9b631
Create Date: 2026-03-31 01:35:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2f3b7a1c8d44"
down_revision: str | Sequence[str] | None = "e7a4c2d9b631"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE_MAPPINGS = (
    {
        "src_table": "profile_cashbox",
        "dst_table": "cashboxes",
        "src_pk": "id",
        "comment": "Cleanup sync mapping for cashboxes.",
        "columns": (
            ("id", "id", None),
            ("profile_id", "profile_id", None),
            ("cash_value", "cash_value", None),
            ("currency", "currency", None),
            ("modify_date", "modify_date", None),
            ("set_default", "set_default", None),
            ("cashbox_name", "cashbox_name", None),
            ("cashbox_name_ru", "cashbox_name_ru", None),
            ("cashbox_name_en", "cashbox_name_en", None),
            ("deleted", "deleted", None),
            ("is_bank", "is_bank", None),
            ("branch_id", "branch_id", None),
            ("is_card", "is_card", None),
            ("print_fiscal", "print_fiscal", None),
        ),
    },
    {
        "src_table": "profiles_client_cards",
        "dst_table": "client_cards",
        "src_pk": "id",
        "comment": "Cleanup sync mapping for client cards.",
        "columns": (
            ("id", "id", None),
            ("profile_id", "profile_id", None),
            ("client_id", "client_id", None),
            ("card_number", "card_number", None),
            ("type", "type", None),
            ("percent", "percent", None),
            ("balance", "balance", None),
            ("deleted", "deleted", None),
            ("created", "created", None),
            ("remote_id", "remote_id", None),
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
