from __future__ import annotations

import uuid
from typing import cast

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'closed', 'archived')",
            name="ck_chats_status",
        ),
        Index("ix_chats_user_profile_created_at", "user_id", "profile_id", "created_at"),
        Index("ix_chats_status_created_at", "status", "created_at"),
        Index("ix_chats_last_message_at", "last_message_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid.uuid4)

    user_id = Column(BigInteger, nullable=False)
    profile_id = Column(BigInteger, nullable=False)
    profile_nick = Column(String(255), nullable=False)

    title = Column(String(255), nullable=True)
    status = Column(String(32), nullable=False, server_default=text("'active'"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_message_at = Column(DateTime(timezone=True), nullable=True)


class ChatEvent(Base):
    __tablename__ = "chat_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('title_updated', 'archived', 'restored', 'deleted')",
            name="ck_chat_events_event_type",
        ),
        Index("ix_chat_events_chat_created_at", "chat_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid.uuid4)
    chat_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
    )

    user_id = Column(BigInteger, nullable=False)
    profile_id = Column(BigInteger, nullable=False)
    profile_nick = Column(String(255), nullable=False)

    actor_user_id = Column(BigInteger, nullable=False)
    old_value_json = Column(JSONB, nullable=True)
    new_value_json = Column(JSONB, nullable=True)
    event_type = Column(String(32), nullable=False)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('started', 'completed', 'failed', 'clarification_needed')",
            name="ck_agent_runs_status",
        ),
        Index("ix_agent_runs_chat_created_at", "chat_id", "created_at"),
        Index("ix_agent_runs_status_created_at", "status", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid.uuid4)
    chat_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(BigInteger, nullable=False)
    profile_id = Column(BigInteger, nullable=False)
    profile_nick = Column(String(255), nullable=False)

    intent = Column(String(255), nullable=True)
    status = Column(String(32), nullable=False, server_default=text("'started'"))

    error_message = Column(Text, nullable=True)
    error_code = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "status IN ('completed', 'onboarding', 'clarify', 'rejected', 'denied', 'failed')",
            name="ck_messages_status",
        ),
        Index("ix_messages_chat_created_at", "chat_id", "created_at"),
        Index("ix_messages_run_id", "run_id"),
        Index("ix_messages_status_created_at", "status", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid.uuid4)
    chat_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    question_text = Column(Text, nullable=False)
    answer_text = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, server_default=text("'completed'"))
    intent = Column(String(255), nullable=True)
    clarification_needed = Column(Boolean, nullable=False, server_default=text("false"))
    error_code = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint(
            "feedback_type IN ('positive', 'negative')",
            name="ck_feedback_feedback_type",
        ),
        Index("ix_feedback_message_id", "message_id"),
        Index("ix_feedback_chat_created_at", "chat_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid.uuid4)

    user_id = Column(BigInteger, nullable=False)
    profile_id = Column(BigInteger, nullable=False)
    profile_nick = Column(String(255), nullable=False)

    chat_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    message_id = Column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )

    feedback_type = Column(String(16), nullable=False)
    comment = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    @property
    def is_positive(self) -> bool:
        return cast(str, self.feedback_type) == "positive"

    @property
    def is_negative(self) -> bool:
        return cast(str, self.feedback_type) == "negative"


class ChatMetadata(Base):
    __tablename__ = "chat_metadata"
    __table_args__ = (
        Index("ix_chat_metadata_chat_key", "chat_id", "key"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid.uuid4)
    chat_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
    )
    key = Column(String(128), nullable=False)
    value_json = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


__all__ = [
    "AgentRun",
    "Base",
    "Chat",
    "ChatEvent",
    "ChatMetadata",
    "Feedback",
    "Message",
]
