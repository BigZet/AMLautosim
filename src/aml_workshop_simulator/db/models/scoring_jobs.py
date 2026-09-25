"""Durable calculation ownership; results publish in a separate transaction."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BigIntVariant, JSONVariant, TZDateTime


class ScoringJob(Base):
    __tablename__ = "scoring_jobs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('queued','running','completed','failed','cancelled')",
            name="ck_scoring_jobs_state",
        ),
        CheckConstraint(
            "done >= 0 AND total >= done AND attempt >= 0",
            name="ck_scoring_jobs_progress",
        ),
        Index(
            "uq_scoring_jobs_active_round",
            "round_id",
            unique=True,
            postgresql_where=text("state IN ('queued','running')"),
        ),
        Index("ix_scoring_jobs_claim", "state", "lease_until", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    round_id: Mapped[int | None] = mapped_column(
        BigIntVariant, ForeignKey("rounds.id", ondelete="SET NULL")
    )
    original_round_id: Mapped[int] = mapped_column(BigIntVariant)
    actor_id: Mapped[int | None] = mapped_column(
        BigIntVariant, ForeignKey("users.id", ondelete="SET NULL")
    )
    request_id: Mapped[str | None] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(16))
    done: Mapped[int] = mapped_column(default=0)
    total: Mapped[int]
    attempt: Mapped[int] = mapped_column(default=0)
    owner: Mapped[UUID | None] = mapped_column(Uuid)
    lease_until: Mapped[datetime | None] = mapped_column(TZDateTime)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONVariant)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant)
    created_at: Mapped[datetime] = mapped_column(TZDateTime)
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime)
