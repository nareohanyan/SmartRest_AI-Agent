"""add source systems, canonical profiles, canonical users, and mapping tables

Revision ID: f2a7c91b4d08
Revises: 2f3b7a1c8d44
Create Date: 2026-04-03 16:30:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a7c91b4d08"
down_revision: str | Sequence[str] | None = "2f3b7a1c8d44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_systems",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("server_name", sa.String(length=255), nullable=False),
        sa.Column("cloud_num", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'active'"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'readonly', 'disabled')",
            name=op.f("ck_source_systems_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_systems")),
    )

    op.create_table(
        "canonical_profiles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_system_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_nick", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'active'"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'deleted')",
            name=op.f("ck_canonical_profiles_status"),
        ),
        sa.ForeignKeyConstraint(
            ["source_system_id"],
            ["source_systems.id"],
            name=op.f("fk_canonical_profiles_source_system_id_source_systems"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_canonical_profiles")),
        sa.UniqueConstraint("profile_nick", name=op.f("uq_canonical_profiles_profile_nick")),
        sa.UniqueConstraint(
            "source_system_id",
            "profile_id",
            name=op.f("uq_canonical_profiles_source_system_profile_id"),
        ),
    )
    op.create_index(
        op.f("ix_canonical_profiles_source_system_id"),
        "canonical_profiles",
        ["source_system_id"],
        unique=False,
    )

    op.create_table(
        "canonical_users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("canonical_profile_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'active'"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'deleted')",
            name=op.f("ck_canonical_users_status"),
        ),
        sa.ForeignKeyConstraint(
            ["canonical_profile_id"],
            ["canonical_profiles.id"],
            name=op.f("fk_canonical_users_canonical_profile_id_canonical_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_canonical_users")),
        sa.UniqueConstraint(
            "canonical_profile_id",
            "user_id",
            name=op.f("uq_canonical_users_profile_user_id"),
        ),
    )
    op.create_index(
        op.f("ix_canonical_users_canonical_profile_id"),
        "canonical_users",
        ["canonical_profile_id"],
        unique=False,
    )

    op.create_table(
        "profile_source_maps",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_system_id", sa.BigInteger(), nullable=False),
        sa.Column("canonical_profile_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_system_id"],
            ["source_systems.id"],
            name=op.f("fk_profile_source_maps_source_system_id_source_systems"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_profile_id"],
            ["canonical_profiles.id"],
            name=op.f("fk_profile_source_maps_canonical_profile_id_canonical_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profile_source_maps")),
        sa.UniqueConstraint(
            "source_system_id",
            "profile_id",
            name=op.f("uq_profile_source_maps_source_system_profile_id"),
        ),
        sa.UniqueConstraint(
            "canonical_profile_id",
            "source_system_id",
            name=op.f("uq_profile_source_maps_canonical_profile_source_system"),
        ),
    )
    op.create_index(
        op.f("ix_profile_source_maps_source_system_id"),
        "profile_source_maps",
        ["source_system_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_profile_source_maps_canonical_profile_id"),
        "profile_source_maps",
        ["canonical_profile_id"],
        unique=False,
    )

    op.create_table(
        "canonical_source_maps",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_system_id", sa.BigInteger(), nullable=False),
        sa.Column("canonical_user_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_system_id"],
            ["source_systems.id"],
            name=op.f("fk_canonical_source_maps_source_system_id_source_systems"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_user_id"],
            ["canonical_users.id"],
            name=op.f("fk_canonical_source_maps_canonical_user_id_canonical_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_canonical_source_maps")),
        sa.UniqueConstraint(
            "source_system_id",
            "profile_id",
            "user_id",
            name=op.f("uq_canonical_source_maps_source_profile_user"),
        ),
        sa.UniqueConstraint(
            "canonical_user_id",
            "source_system_id",
            name=op.f("uq_canonical_source_maps_canonical_user_source"),
        ),
    )
    op.create_index(
        op.f("ix_canonical_source_maps_source_system_id"),
        "canonical_source_maps",
        ["source_system_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_canonical_source_maps_canonical_user_id"),
        "canonical_source_maps",
        ["canonical_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_canonical_source_maps_canonical_user_id"), table_name="canonical_source_maps")
    op.drop_index(op.f("ix_canonical_source_maps_source_system_id"), table_name="canonical_source_maps")
    op.drop_table("canonical_source_maps")
    op.drop_index(op.f("ix_profile_source_maps_canonical_profile_id"), table_name="profile_source_maps")
    op.drop_index(op.f("ix_profile_source_maps_source_system_id"), table_name="profile_source_maps")
    op.drop_table("profile_source_maps")
    op.drop_index(op.f("ix_canonical_users_canonical_profile_id"), table_name="canonical_users")
    op.drop_table("canonical_users")
    op.drop_index(op.f("ix_canonical_profiles_source_system_id"), table_name="canonical_profiles")
    op.drop_table("canonical_profiles")
    op.drop_table("source_systems")
