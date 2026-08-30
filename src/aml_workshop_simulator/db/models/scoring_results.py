from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BigIntVariant, JSONVariant, TZDateTime


class ScoringResult(Base):
    __tablename__ = 'scoring_results'
    __table_args__ = (
        UniqueConstraint(
            'scenario_id',
            name='uq_scoring_results_scenario_id'),
    )
    id: Mapped[int] = mapped_column(
        BigIntVariant,
        primary_key=True,
        autoincrement=True)
    scenario_id: Mapped[int] = mapped_column(
        BigIntVariant, ForeignKey('scenarios.id'))
    risk_score: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    risk_label: Mapped[str] = mapped_column(String)
    stealth_score: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    resource_score: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    game_score: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    explanation: Mapped[dict[str, Any]] = mapped_column(JSONVariant)
    scoring_version: Mapped[str] = mapped_column(String)
    leaderboard_version: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(TZDateTime)
