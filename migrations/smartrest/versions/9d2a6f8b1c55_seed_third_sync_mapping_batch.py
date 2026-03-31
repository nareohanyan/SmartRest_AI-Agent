"""seed third sync mapping batch

Revision ID: 9d2a6f8b1c55
Revises: c4f2a9d7e6b3
Create Date: 2026-03-31 01:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9d2a6f8b1c55"
down_revision: str | Sequence[str] | None = "c4f2a9d7e6b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE_MAPPINGS = (
    {
        "src_table": "st_document",
        "dst_table": "documents",
        "src_pk": "id",
        "comment": "Third sync batch mapping for documents.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
            ("company_id", "company_id", None),
            ("type_id", "type_id", None),
            ("status_id", "status_id", None),
            ("order_id", "order_id", None),
            ("branch_id", "branch_id", None),
            ("back_date", "back_date", None),
            ("identification_number", "identification_number", None),
        ),
    },
    {
        "src_table": "st_document_content",
        "dst_table": "document_contents",
        "src_pk": "id",
        "comment": "Third sync batch mapping for document contents.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
            ("document_id", "document_id", None),
            ("store_id", "store_id", None),
            ("material_content_id", "material_content_id", None),
            ("quantity_in", "quantity_in", None),
            ("quantity_out", "quantity_out", None),
            ("price", "price", None),
            ("branch_id", "branch_id", None),
            ("referer_id", "referer_id", None),
            ("fifo_state_id", "fifo_state_id", None),
            ("useful_weight_quantity", "useful_weight_quantity", None),
            ("st_balance_create_status", "st_balance_create_status", None),
        ),
    },
    {
        "src_table": "st_document_type",
        "dst_table": "document_types",
        "src_pk": "id",
        "comment": "Third sync batch mapping for document types.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
            ("automatic", "automatic", None),
            ("order_in", "order_in", None),
        ),
    },
    {
        "src_table": "st_document_type_template",
        "dst_table": "document_type_template",
        "src_pk": "id",
        "comment": "Third sync batch mapping for document type templates.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
            ("document_type_id", "document_type_id", None),
            ("name", "name", None),
        ),
    },
    {
        "src_table": "st_material",
        "dst_table": "materials",
        "src_pk": "id",
        "comment": "Third sync batch mapping for materials.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
            ("material_category_id", "material_category_id", None),
            ("semi_finished", "semi_finished", None),
            ("useful_weight", "useful_weight", None),
        ),
    },
    {
        "src_table": "st_material_content",
        "dst_table": "material_content",
        "src_pk": "id",
        "comment": "Third sync batch mapping for material content.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
            ("material_id", "material_id", None),
            ("unit_id", "unit_id", None),
            ("price", "price", None),
            ("min_quantity", "min_quantity", None),
            ("code", "code", None),
            ("product_balance", "product_balance", None),
            ("pre_pack_mass", "pre_pack_mass", None),
        ),
    },
    {
        "src_table": "st_material_category",
        "dst_table": "material_category",
        "src_pk": "id",
        "comment": "Third sync batch mapping for material categories.",
        "columns": (
            ("id", "id", None),
            ("created_at", "created_at", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
            ("profile_id", "profile_id", None),
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
