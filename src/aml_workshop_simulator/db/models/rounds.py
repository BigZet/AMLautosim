from datetime import datetime
from typing import Any
from sqlalchemy import String, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, BigIntVariant, TZDateTime, JSONVariant


class Round(Base):
    __tablename__ = 'rounds'
    id: Mapped[int] = mapped_column(
        BigIntVariant,
        primary_key=True,
        autoincrement=True)
    title: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True)
    config_revision: Mapped[int] = mapped_column(Integer)
    game_config: Mapped[dict[str, Any]] = mapped_column(JSONVariant)
    scoring_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSONVariant, nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(
        BigIntVariant, ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(TZDateTime)
    activated_at: Mapped[datetime | None] = mapped_column(
        TZDateTime, nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(
        TZDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        TZDateTime, nullable=True)
    # A restart never deletes anything: it creates a new round that points
    # back at the one it replaced.
    restarted_from_round_id: Mapped[int | None] = mapped_column(
        BigIntVariant, ForeignKey('rounds.id'), nullable=True)
    preset_id: Mapped[int | None] = mapped_column(
        BigIntVariant, ForeignKey('round_presets.id', ondelete='SET NULL'),
        nullable=True)
