from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BigIntVariant, JSONVariant, TZDateTime


class ActionCard(Base):
    __tablename__ = "action_cards"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_action_cards_version"),
        CheckConstraint(
            "energy_cost >= 0 AND time_cost >= 0", name="ck_action_cards_costs"
        ),
        CheckConstraint(
            "min_amount > 0 AND min_amount <= max_amount",
            name="ck_action_cards_amounts",
        ),
        CheckConstraint(
            "fee_rate >= 0 AND fee_rate <= 1", name="ck_action_cards_fee_rate"
        ),
        CheckConstraint(
            "requires_card_code IS NULL OR requires_card_code <> code",
            name="ck_action_cards_requires_other_card",
        ),
        UniqueConstraint("code", "version", name="uq_action_cards_code_version"),
    )
    id: Mapped[int] = mapped_column(BigIntVariant, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    flow: Mapped[str] = mapped_column(String)
    risk_weight: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    energy_cost: Mapped[int] = mapped_column(Integer)
    time_cost: Mapped[int] = mapped_column(Integer)
    fee_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    min_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    max_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    requires_card_code: Mapped[str | None] = mapped_column(String, nullable=True)
    parameter_schema: Mapped[dict[str, Any]] = mapped_column(JSONVariant)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime)
