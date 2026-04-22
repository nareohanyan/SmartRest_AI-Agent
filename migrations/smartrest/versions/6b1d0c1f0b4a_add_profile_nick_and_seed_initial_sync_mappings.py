"""add profile_nick and seed initial sync mappings

Revision ID: 6b1d0c1f0b4a
Revises: 5d6ef69f5b21
Create Date: 2026-03-31 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6b1d0c1f0b4a"
down_revision: str | Sequence[str] | None = "5d6ef69f5b21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLE_MAPPINGS = (
    {
        "src_table": "profiles",
        "dst_table": "profiles",
        "src_pk": "id",
        "comment": "Initial sync mapping for profile identities and billing data.",
        "columns": (
            ("id", "id", None),
            ("name", "name", None),
            ("nic", "profile_nick", None),
            ("billing_status", "billing_status", None),
            ("billing_start_time", "billing_start_time", None),
            ("billing_end_time", "billing_end_time", None),
            ("currency", "currency", None),
        ),
    },
    {
        "src_table": "profiles_users",
        "dst_table": "users",
        "src_pk": "id",
        "comment": "Initial sync mapping for user permission identities.",
        "columns": (
            ("id", "id", None),
            ("profile_id", "profile_id", None),
            ("username", "username", None),
            ("status", "status", None),
            ("reports", "reports", None),
            ("role_id", "role_id", None),
            ("deleted", "deleted", None),
        ),
    },
    {
        "src_table": "profiles_hall",
        "dst_table": "halls",
        "src_pk": "id",
        "comment": "Initial sync mapping for hall references.",
        "columns": (
            ("id", "id", None),
            ("profile_id", "profile_id", None),
            ("name", "name", None),
            ("deleted", "deleted", None),
            ("branch_id", "branch_id", None),
            ("floor_id", "floor_id", None),
        ),
    },
    {
        "src_table": "profiles_staff",
        "dst_table": "staff",
        "src_pk": "id",
        "comment": "Initial sync mapping for staff references.",
        "columns": (
            ("id", "id", None),
            ("profile_id", "profile_id", None),
            ("firstname", "firstname", None),
            ("lastname", "lastname", None),
            ("position", "position", None),
            ("deleted", "deleted", None),
            ("salary_value", "salary_value", None),
            ("dismission_date", "dismission_date", None),
        ),
    },
    {
        "src_table": "profiles_breake_points",
        "dst_table": "break_points",
        "src_pk": "id",
        "comment": "Initial sync mapping for source break point references.",
        "columns": (
            ("id", "id", None),
            ("profile_id", "profile_id", None),
            ("date", "date", None),
            ("branch_id", "branch_id", None),
        ),
    },
    {
        "src_table": "profiles_log",
        "dst_table": "logs",
        "src_pk": "id",
        "comment": "Initial sync mapping for operational logs.",
        "columns": (
            ("id", "id", None),
            ("profile_id", "profile_id", None),
            ("user_id", "user_id", None),
            ("category", "category", None),
            ("action", "action", None),
            ("date", "date", None),
            ("branch_id", "branch_id", None),
            ("deleted", "deleted", None),
            ("archived", "archived", None),
        ),
    },
    {
        "src_table": "profiles_room_table",
        "dst_table": "tables",
        "src_pk": "id",
        "comment": "Initial sync mapping for room tables.",
        "columns": (
            ("id", "id", None),
            ("profile_id", "profile_id", None),
            ("room_table_name", "room_table_name", None),
            ("hall_id", "hall_id", None),
            ("delivery", "delivery", None),
            ("service_commissions_type", "service_commissions_type", None),
            ("service_commissions_value", "service_commissions_value", None),
            ("max_people", "max_people", None),
            ("branch_id", "branch_id", None),
            ("deleted", "deleted", None),
            ("hotel_room_status", "hotel_room_status", None),
        ),
    },
)


def upgrade() -> None:
    op.add_column("profiles", sa.Column("profile_nick", sa.String(length=255), nullable=True))

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

    op.drop_column("profiles", "profile_nick")
