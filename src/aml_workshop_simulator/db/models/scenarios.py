import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import String, Integer, ForeignKey, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, BigIntVariant, TZDateTime, JSONVariant


class Scenario(Base):
    __tablename__ = 'scenarios'
    __table_args__ = (
        UniqueConstraint(
            'round_id',
            'participant_id',
            name='uq_scenarios_round_id_participant_id'),
    )
    id: Mapped[int] = mapped_column(
        BigIntVariant,
        primary_key=True,
        autoincrement=True)
    round_id: Mapped[int] = mapped_column(
        BigIntVariant, ForeignKey('rounds.id'))
    participant_id: Mapped[int] = mapped_column(
        BigIntVariant, ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String, index=True)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant)
    resource_snapshot: Mapped[dict[str, Any] |
                              None] = mapped_column(JSONVariant, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    last_client_mutation_id: Mapped[uuid.UUID |
                                    None] = mapped_column(Uuid, nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime)
    submitted_at: Mapped[datetime | None] = mapped_column(
        TZDateTime, nullable=True)
    # Pointers into the append-only scenario_versions history.
    current_version_id: Mapped[int | None] = mapped_column(
        BigIntVariant, nullable=True)
    submitted_version_id: Mapped[int | None] = mapped_column(
        BigIntVariant, nullable=True)
