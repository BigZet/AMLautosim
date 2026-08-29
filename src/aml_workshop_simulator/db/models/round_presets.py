"""Reusable round configurations prepared before a workshop.

A preset is a template only: creating a round copies its `game_config` into the
round's own snapshot, so editing the preset afterwards never changes a round
that already exists.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BigIntVariant, JSONVariant, TZDateTime


class RoundPreset(Base):
    __tablename__ = 'round_presets'
    id: Mapped[int] = mapped_column(
        BigIntVariant, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    game_config: Mapped[dict[str, Any]] = mapped_column(JSONVariant)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_by_user_id: Mapped[int] = mapped_column(
        BigIntVariant, ForeignKey('users.id'))
    updated_by_user_id: Mapped[int] = mapped_column(
        BigIntVariant, ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(TZDateTime)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime)
