"""add ai agent subscription fields

Revision ID: 5d6ef69f5b21
Revises: d395f2ffc1d3
Create Date: 2026-03-30 15:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5d6ef69f5b21"
down_revision: str | Sequence[str] | None = "d395f2ffc1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column(
            "ai_agent_subscription_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'expired'"),
        ),
    )
    op.add_column(
        "profiles",
        sa.Column("ai_agent_subscription_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_profiles_ai_agent_subscription_status",
        "profiles",
        "ai_agent_subscription_status IN "
        "('active', 'trial', 'expired', 'cancelled', 'suspended')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_profiles_ai_agent_subscription_status", "profiles", type_="check")
    op.drop_column("profiles", "ai_agent_subscription_expires_at")
    op.drop_column("profiles", "ai_agent_subscription_status")
