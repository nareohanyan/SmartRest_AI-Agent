"""fix language translation ids to strings

Revision ID: 7c8d9e1f2a34
Revises: a3e91b7c4d2f
Create Date: 2026-04-13 16:20:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c8d9e1f2a34"
down_revision: str | Sequence[str] | None = "a3e91b7c4d2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _alter_language_id_to_string(table_name: str) -> None:
    op.alter_column(
        table_name,
        "language_id",
        existing_type=sa.BigInteger(),
        type_=sa.String(length=255),
        existing_nullable=True,
        postgresql_using="language_id::text",
    )


def _alter_language_id_to_bigint(table_name: str) -> None:
    op.alter_column(
        table_name,
        "language_id",
        existing_type=sa.String(length=255),
        type_=sa.BigInteger(),
        existing_nullable=True,
        postgresql_using="NULLIF(language_id, '')::bigint",
    )


def upgrade() -> None:
    _alter_language_id_to_string("material_category_language")
    _alter_language_id_to_string("material_language")
    _alter_language_id_to_string("store_language")
    _alter_language_id_to_string("unit_language")


def downgrade() -> None:
    _alter_language_id_to_bigint("unit_language")
    _alter_language_id_to_bigint("store_language")
    _alter_language_id_to_bigint("material_language")
    _alter_language_id_to_bigint("material_category_language")
