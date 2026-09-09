"""Resolved card contracts for UI forms."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.db.models.action_cards import ActionCard
from src.aml_workshop_simulator.db.queries import get_round
from src.aml_workshop_simulator.schemas.rounds import ActionCardOut
from src.aml_workshop_simulator.services.projections import card_out
from src.aml_workshop_simulator.services.scenario_service import (
    load_round_card_specs,
    round_policy,
)


async def catalog_cards(db: AsyncSession) -> list[ActionCardOut]:
    cards = (
        (
            await db.execute(
                select(ActionCard).where(ActionCard.is_active).order_by(ActionCard.id)
            )
        )
        .scalars()
        .all()
    )
    return [card_out(row) for row in cards]


async def round_cards(db: AsyncSession, round_id: int) -> list[ActionCardOut]:
    row = await get_round(db, round_id)
    specs = load_round_card_specs(row)
    policy = round_policy(row, specs)
    return [
        card_out(spec, policy.for_card(spec.key))
        for spec in sorted(specs.values(), key=lambda spec: spec.id)
    ]
