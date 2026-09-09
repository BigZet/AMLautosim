"""Shared queries. Callers own the transaction and acquire round locks first."""

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.core.errors import AccountBlocked, NotFound
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.db.models.users import User


async def get_round(
    db: AsyncSession, round_id: int, *, lock: Literal["share", "update"] | None = None
) -> Round:
    query = select(Round).where(Round.id == round_id)
    if lock:
        query = query.with_for_update(read=lock == "share")
    # Refresh a previously loaded object after waiting for another transaction.
    row = (
        await db.execute(query.execution_options(populate_existing=True))
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("Раунд не найден или перезапущен.", code="round_not_found")
    return row


async def get_scenario(
    db: AsyncSession, round_id: int, participant_id: int, *, lock: bool = False
) -> Scenario | None:
    if lock:
        # A user row also exists before the first autosave, unlike a scenario row.
        user = (
            await db.execute(
                select(User)
                .where(User.id == participant_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        if user.is_blocked:
            raise AccountBlocked("Доступ к учетной записи заблокирован организатором.")
    query = select(Scenario).where(
        Scenario.round_id == round_id, Scenario.participant_id == participant_id
    )
    if lock:
        query = query.with_for_update()
    return (
        await db.execute(query.execution_options(populate_existing=True))
    ).scalar_one_or_none()
