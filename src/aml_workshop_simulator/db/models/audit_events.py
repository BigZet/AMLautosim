from datetime import datetime
from typing import Any
from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, BigIntVariant, TZDateTime, JSONVariant


class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id: Mapped[int] = mapped_column(
        BigIntVariant,
        primary_key=True,
        autoincrement=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        BigIntVariant, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    round_id: Mapped[int | None] = mapped_column(
        BigIntVariant, ForeignKey('rounds.id'), nullable=True)
    scenario_id: Mapped[int | None] = mapped_column(
        BigIntVariant, ForeignKey('scenarios.id'), nullable=True)
    event_type: Mapped[str] = mapped_column(String)
    target_type: Mapped[str | None] = mapped_column(String, nullable=True)
    target_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    idempotency_key_hash: Mapped[str | None] = mapped_column(
        String, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        'metadata', JSONVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime)
