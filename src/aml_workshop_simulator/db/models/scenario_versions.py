"""Append-only history of every explicitly saved draft.

`scenarios` keeps the pointers (`current_version_id`, `submitted_version_id`)
and the optimistic-concurrency counter; the chain itself always lives in an
immutable `scenario_versions` row. Restoring an older draft appends a *new*
version whose steps are copied from it, so nothing that was saved later is ever
lost, and scoring only ever reads the row the participant submitted.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BigIntVariant, JSONVariant, TZDateTime


class ScenarioVersion(Base):
    __tablename__ = 'scenario_versions'
    __table_args__ = (
        UniqueConstraint(
            'scenario_id', 'revision', name='uq_scenario_versions_scenario_revision'
        ),
    )
    id: Mapped[int] = mapped_column(
        BigIntVariant, primary_key=True, autoincrement=True)
    scenario_id: Mapped[int] = mapped_column(
        BigIntVariant, ForeignKey('scenarios.id', ondelete='CASCADE'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant)
    resource_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSONVariant, nullable=True)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    restored_from_revision: Mapped[int | None] = mapped_column(
        Integer, nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(
        BigIntVariant, ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(TZDateTime)
