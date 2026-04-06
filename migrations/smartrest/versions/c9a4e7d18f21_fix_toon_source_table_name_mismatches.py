"""fix toon source table name mismatches

Revision ID: c9a4e7d18f21
Revises: b6c1e4d2a9f0
Create Date: 2026-04-06 16:10:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9a4e7d18f21"
down_revision: str | Sequence[str] | None = "b6c1e4d2a9f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE migrations.table_map
            SET src_table = 'profle_cashbox'
            WHERE src_table = 'profile_cashbox'
              AND dst_table = 'cashboxes'
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE migrations.table_map
            SET src_table = 'profiles_clients_cards'
            WHERE src_table = 'profiles_client_cards'
              AND dst_table = 'client_cards'
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE migrations.table_map
            SET src_table = 'profile_cashbox'
            WHERE src_table = 'profle_cashbox'
              AND dst_table = 'cashboxes'
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE migrations.table_map
            SET src_table = 'profiles_client_cards'
            WHERE src_table = 'profiles_clients_cards'
              AND dst_table = 'client_cards'
            """
        )
    )

