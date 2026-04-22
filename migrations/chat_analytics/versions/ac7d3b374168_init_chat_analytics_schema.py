"""Init chat analytics schema

Revision ID: ac7d3b374168
Revises:
Create Date: 2026-03-13 17:46:31.003374

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ac7d3b374168"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "chats",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_nick", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'closed', 'archived')",
            name="ck_chats_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chats_last_message_at", "chats", ["last_message_at"], unique=False)
    op.create_index(
        "ix_chats_status_created_at",
        "chats",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_chats_user_profile_created_at",
        "chats",
        ["user_id", "profile_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "chat_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("chat_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_nick", sa.String(length=255), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=False),
        sa.Column("old_value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('title_updated', 'archived', 'restored', 'deleted')",
            name="ck_chat_events_event_type",
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_events_chat_created_at",
        "chat_events",
        ["chat_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("chat_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_nick", sa.String(length=255), nullable=False),
        sa.Column("intent", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'started'"),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('started', 'completed', 'failed', 'clarification_needed')",
            name="ck_agent_runs_status",
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_runs_chat_created_at",
        "agent_runs",
        ["chat_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_status_created_at",
        "agent_runs",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("chat_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'completed'"),
            nullable=False,
        ),
        sa.Column("intent", sa.String(length=255), nullable=True),
        sa.Column(
            "clarification_needed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'onboarding', 'clarify', 'rejected', 'denied', 'failed')",
            name="ck_messages_status",
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_run_id", "messages", ["run_id"], unique=False)
    op.create_index(
        "ix_messages_chat_created_at",
        "messages",
        ["chat_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_messages_status_created_at",
        "messages",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "feedback",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_nick", sa.String(length=255), nullable=False),
        sa.Column("chat_id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("feedback_type", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "feedback_type IN ('positive', 'negative')",
            name="ck_feedback_feedback_type",
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feedback_message_id", "feedback", ["message_id"], unique=False)
    op.create_index(
        "ix_feedback_chat_created_at",
        "feedback",
        ["chat_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "chat_metadata",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("chat_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_metadata_chat_key",
        "chat_metadata",
        ["chat_id", "key"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_chat_metadata_chat_key", table_name="chat_metadata")
    op.drop_table("chat_metadata")
    op.drop_index("ix_feedback_chat_created_at", table_name="feedback")
    op.drop_index("ix_feedback_message_id", table_name="feedback")
    op.drop_table("feedback")
    op.drop_index("ix_messages_status_created_at", table_name="messages")
    op.drop_index("ix_messages_chat_created_at", table_name="messages")
    op.drop_index("ix_messages_run_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_agent_runs_status_created_at", table_name="agent_runs")
    op.drop_index("ix_agent_runs_chat_created_at", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_chat_events_chat_created_at", table_name="chat_events")
    op.drop_table("chat_events")
    op.drop_index("ix_chats_user_profile_created_at", table_name="chats")
    op.drop_index("ix_chats_status_created_at", table_name="chats")
    op.drop_index("ix_chats_last_message_at", table_name="chats")
    op.drop_table("chats")
