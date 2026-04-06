"""fix toon column name mismatches in mapping metadata

Revision ID: f4d0a6e2b1c3
Revises: c9a4e7d18f21
Create Date: 2026-04-06 14:20:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4d0a6e2b1c3"
down_revision: str | Sequence[str] | None = "c9a4e7d18f21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE migrations.column_map cm
            SET src_column = 'surname'
            FROM migrations.table_map tm
            WHERE cm.table_map_id = tm.id
              AND tm.src_table = 'profiles_staff'
              AND tm.dst_table = 'staff'
              AND cm.src_column = 'lastname'
              AND cm.dst_column = 'lastname'
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE migrations.column_map cm
            SET src_column = 'mod_date'
            FROM migrations.table_map tm
            WHERE cm.table_map_id = tm.id
              AND tm.src_table = 'profle_cashbox'
              AND tm.dst_table = 'cashboxes'
              AND cm.src_column = 'modify_date'
              AND cm.dst_column = 'modify_date'
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE migrations.column_map cm
            SET src_column = 'create_date'
            FROM migrations.table_map tm
            WHERE cm.table_map_id = tm.id
              AND tm.src_table = 'profiles_clients_cards'
              AND tm.dst_table = 'client_cards'
              AND cm.src_column = 'created'
              AND cm.dst_column = 'created'
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE migrations.column_map cm
            SET src_column = 'lastname'
            FROM migrations.table_map tm
            WHERE cm.table_map_id = tm.id
              AND tm.src_table = 'profiles_staff'
              AND tm.dst_table = 'staff'
              AND cm.src_column = 'surname'
              AND cm.dst_column = 'lastname'
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE migrations.column_map cm
            SET src_column = 'modify_date'
            FROM migrations.table_map tm
            WHERE cm.table_map_id = tm.id
              AND tm.src_table = 'profle_cashbox'
              AND tm.dst_table = 'cashboxes'
              AND cm.src_column = 'mod_date'
              AND cm.dst_column = 'modify_date'
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE migrations.column_map cm
            SET src_column = 'created'
            FROM migrations.table_map tm
            WHERE cm.table_map_id = tm.id
              AND tm.src_table = 'profiles_clients_cards'
              AND tm.dst_table = 'client_cards'
              AND cm.src_column = 'create_date'
              AND cm.dst_column = 'created'
            """
        )
    )

