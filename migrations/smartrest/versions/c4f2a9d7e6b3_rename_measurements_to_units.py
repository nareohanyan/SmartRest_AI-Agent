"""rename measurements to units

Revision ID: c4f2a9d7e6b3
Revises: 1b8c4f6e2d91
Create Date: 2026-03-31 00:45:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4f2a9d7e6b3"
down_revision: str | Sequence[str] | None = "1b8c4f6e2d91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rename_index(old_name: str, new_name: str) -> None:
    op.execute(f'ALTER INDEX "{old_name}" RENAME TO "{new_name}"')


def upgrade() -> None:
    op.rename_table("measurements", "units")
    _rename_index("ix_measurements_profile_id", "ix_units_profile_id")

    op.rename_table("measurements_lng", "unit_language")
    _rename_index("ix_measurements_lng_profile_id", "ix_unit_language_profile_id")
    _rename_index("ix_measurements_lng_unit_id", "ix_unit_language_unit_id")


def downgrade() -> None:
    _rename_index("ix_unit_language_unit_id", "ix_measurements_lng_unit_id")
    _rename_index("ix_unit_language_profile_id", "ix_measurements_lng_profile_id")
    op.rename_table("unit_language", "measurements_lng")

    _rename_index("ix_units_profile_id", "ix_measurements_profile_id")
    op.rename_table("units", "measurements")
