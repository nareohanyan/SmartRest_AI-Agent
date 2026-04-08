"""drop unique constraint on orders.profile_order_uniq_id

Revision ID: a3e91b7c4d2f
Revises: f4d0a6e2b1c3
Create Date: 2026-04-07 15:20:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3e91b7c4d2f"
down_revision: str | Sequence[str] | None = "f4d0a6e2b1c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE_NAME = "orders"
_UNIQUE_CONSTRAINT_NAME = "uq_orders_profile_order_uniq_id"
_INDEX_NAME = "ix_orders_profile_order_uniq_id"
_COLUMN_NAME = "profile_order_uniq_id"


def _has_unique_constraint(bind: sa.engine.Connection) -> bool:
    inspector = sa.inspect(bind)
    return any(
        constraint.get("name") == _UNIQUE_CONSTRAINT_NAME
        for constraint in inspector.get_unique_constraints(_TABLE_NAME)
    )


def _has_index(bind: sa.engine.Connection) -> bool:
    inspector = sa.inspect(bind)
    return any(
        index.get("name") == _INDEX_NAME
        for index in inspector.get_indexes(_TABLE_NAME)
    )


def upgrade() -> None:
    bind = op.get_bind()
    if _has_unique_constraint(bind):
        op.drop_constraint(_UNIQUE_CONSTRAINT_NAME, _TABLE_NAME, type_="unique")
    if not _has_index(bind):
        op.create_index(_INDEX_NAME, _TABLE_NAME, [_COLUMN_NAME], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if _has_index(bind):
        op.drop_index(_INDEX_NAME, table_name=_TABLE_NAME)
    if not _has_unique_constraint(bind):
        op.create_unique_constraint(_UNIQUE_CONSTRAINT_NAME, _TABLE_NAME, [_COLUMN_NAME])
