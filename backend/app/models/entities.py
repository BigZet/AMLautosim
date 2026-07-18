from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.session import Base
from backend.app.domain.enums import RiskLabel, RoundStatus, ScenarioStatus, UserRole


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.participant)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    scenarios: Mapped[list["Scenario"]] = relationship(back_populates="participant")


class ActionCard(Base):
    __tablename__ = "action_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(80))
    risk_weight: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Round(Base):
    __tablename__ = "rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    status: Mapped[RoundStatus] = mapped_column(Enum(RoundStatus), default=RoundStatus.draft)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    scenarios: Mapped[list["Scenario"]] = relationship(back_populates="round")


class Scenario(Base):
    __tablename__ = "scenarios"
    __table_args__ = (UniqueConstraint("round_id", "participant_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("rounds.id"), index=True)
    participant_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[ScenarioStatus] = mapped_column(
        Enum(ScenarioStatus), default=ScenarioStatus.draft, index=True
    )
    steps: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    round: Mapped[Round] = relationship(back_populates="scenarios")
    participant: Mapped[User] = relationship(back_populates="scenarios")
    result: Mapped["ScoringResult | None"] = relationship(back_populates="scenario", uselist=False)


class ScoringResult(Base):
    __tablename__ = "scoring_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id"), unique=True, index=True)
    risk_score: Mapped[float] = mapped_column(Float)
    label: Mapped[RiskLabel] = mapped_column(Enum(RiskLabel))
    explanation: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    scenario: Mapped[Scenario] = relationship(back_populates="result")
