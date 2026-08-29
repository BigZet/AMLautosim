from datetime import datetime
from decimal import Decimal
from sqlalchemy import Integer, String, Numeric, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, BigIntVariant, TZDateTime


class LeaderboardAdjustment(Base):
    __tablename__ = 'leaderboard_adjustments'
    __table_args__ = (
        UniqueConstraint(
            'scenario_id',
            name='uq_leaderboard_adjustments_scenario_id'),
    )
    id: Mapped[int] = mapped_column(
        BigIntVariant,
        primary_key=True,
        autoincrement=True)
    scenario_id: Mapped[int] = mapped_column(
        BigIntVariant, ForeignKey('scenarios.id'))
    admin_user_id: Mapped[int] = mapped_column(
        BigIntVariant, ForeignKey('users.id'))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    risk_score_override: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True)
    resource_score_override: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True)
    game_score_override: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True)
    reason: Mapped[str] = mapped_column(String(500))
    updated_at: Mapped[datetime] = mapped_column(TZDateTime)
