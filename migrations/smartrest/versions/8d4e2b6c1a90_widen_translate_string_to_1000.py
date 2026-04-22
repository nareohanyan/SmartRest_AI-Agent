"""widen translate string to 1000

Revision ID: 8d4e2b6c1a90
Revises: 7c8d9e1f2a34
Create Date: 2026-04-13 17:05:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8d4e2b6c1a90"
down_revision: str | Sequence[str] | None = "7c8d9e1f2a34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "translate",
        "string",
        existing_type=sa.String(length=255),
        type_=sa.String(length=1000),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "translate",
        "string",
        existing_type=sa.String(length=1000),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
