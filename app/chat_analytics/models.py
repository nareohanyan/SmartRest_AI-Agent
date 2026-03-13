from __future__ import annotations

import uuid

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


class Thread(Base):
    __tablename__ = "threads"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'closed', 'archived')",
            name="ck_threads_status",
        ),
        Index("ix_threads_user_profile_created_at", "user_id", "profile_id", "created_at"),
        Index("ix_threads_status_created_at", "status", "created_at"),
        Index("ix_threads_last_message_at", "last_message_at"),
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

    metadata_json = Column(JSONB, nullable=True)

class ThreadHistory(Base):
    __tablename__ = "thread_history"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('title_updated', 'archived', 'restored', 'deleted')",
            name="ck_threads_history_event_type",
        ),
        Index("ix_threads_history_thread_created_at", "thread_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid.uuid4)

    thread_id = Column(UUID(as_uuid=True), ForeignKey("threads.id"), nullable=False)

    user_id = Column(BigInteger, nullable=False)
    profile_id = Column(BigInteger, nullable=False)
    profile_nick = Column(String(255), nullable=False)

    changed_by_user_id = Column(BigInteger, nullable=False)
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
        Index("ix_agent_runs_thread_created_at", "thread_id", "created_at"),
        Index("ix_agent_runs_status_created_at", "status", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid.uuid4)

    thread_id = Column(UUID(as_uuid=True), ForeignKey("threads.id"), nullable=False)
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
        Index("ix_messages_thread_created_at", "thread_id", "created_at"),
        Index("ix_messages_run_id", "run_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid.uuid4)

    thread_id = Column(UUID(as_uuid=True), ForeignKey("threads.id"), nullable=False)
    run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=False)

    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = ()

    id = Column(UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid.uuid4)

    user_id = Column(BigInteger, nullable=False)
    profile_id = Column(BigInteger, nullable=False)
    profile_nick = Column(String(255), nullable=False)

    thread_id = Column(UUID(as_uuid=True), ForeignKey("threads.id"), nullable=False)
    run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=False)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id"), nullable=False)

    is_positive = Column(Boolean, nullable=False, server_default=text("'0'"))
    is_negative = Column(Boolean, nullable=False, server_default=text("'0'"))

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )