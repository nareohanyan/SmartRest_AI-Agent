"""add sync operational tables

Revision ID: b6c1e4d2a9f0
Revises: f2a7c91b4d08
Create Date: 2026-04-06 15:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b6c1e4d2a9f0"
down_revision: str | Sequence[str] | None = "f2a7c91b4d08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sync_state",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_system_id", sa.BigInteger(), nullable=False),
        sa.Column("stream_name", sa.String(length=128), nullable=False),
        sa.Column("last_cursor", sa.BigInteger(), nullable=True),
        sa.Column("last_synced_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_system_id"],
            ["source_systems.id"],
            name=op.f("fk_sync_state_source_system_id_source_systems"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_state")),
        sa.UniqueConstraint(
            "source_system_id",
            "stream_name",
            name=op.f("uq_sync_state_source_stream"),
        ),
    )
    op.create_index(
        op.f("ix_sync_state_source_system_id"),
        "sync_state",
        ["source_system_id"],
        unique=False,
    )

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_system_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'running'"), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("profiles_processed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("users_processed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("errors_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'partial', 'failed')",
            name=op.f("ck_sync_runs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["source_system_id"],
            ["source_systems.id"],
            name=op.f("fk_sync_runs_source_system_id_source_systems"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_runs")),
    )
    op.create_index(
        op.f("ix_sync_runs_source_system_id"),
        "sync_runs",
        ["source_system_id"],
        unique=False,
    )

    op.create_table(
        "sync_errors",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("sync_run_id", sa.BigInteger(), nullable=False),
        sa.Column("source_system_id", sa.BigInteger(), nullable=False),
        sa.Column("stream_name", sa.String(length=128), nullable=False),
        sa.Column("entity_key", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("payload_fragment", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_system_id"],
            ["source_systems.id"],
            name=op.f("fk_sync_errors_source_system_id_source_systems"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["sync_runs.id"],
            name=op.f("fk_sync_errors_sync_run_id_sync_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_errors")),
    )
    op.create_index(
        op.f("ix_sync_errors_source_system_id"),
        "sync_errors",
        ["source_system_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sync_errors_sync_run_id"),
        "sync_errors",
        ["sync_run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_sync_errors_sync_run_id"), table_name="sync_errors")
    op.drop_index(op.f("ix_sync_errors_source_system_id"), table_name="sync_errors")
    op.drop_table("sync_errors")
    op.drop_index(op.f("ix_sync_runs_source_system_id"), table_name="sync_runs")
    op.drop_table("sync_runs")
    op.drop_index(op.f("ix_sync_state_source_system_id"), table_name="sync_state")
    op.drop_table("sync_state")

