from __future__ import annotations

from enum import Enum

from app.schemas.base import SchemaModel


class AIAgentSubscriptionStatus(str, Enum):
    ACTIVE = "active"
    TRIAL = "trial"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    SUSPENDED = "suspended"


class SubscriptionAccessDecision(SchemaModel):
    allowed: bool
    reason_code: str
    reason_message: str
