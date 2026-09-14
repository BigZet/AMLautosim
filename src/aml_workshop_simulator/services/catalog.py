"""Resolved card contracts for UI forms."""

from sqlalchemy import select
from src.aml_workshop_simulator.domain.catalog import CARD_CODES
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.db.models.action_cards import ActionCard
from src.aml_workshop_simulator.domain.contract_versions import contract_version
from src.aml_workshop_simulator.db.queries import get_round
from src.aml_workshop_simulator.schemas.rounds import ActionCardOut
from src.aml_workshop_simulator.services.projections import card_out
from src.aml_workshop_simulator.services.scenario_service import (
    load_round_card_specs,
    round_policy,
)


async def catalog_cards(
    db: AsyncSession, *, schema_version: int = 7
) -> list[ActionCardOut]:
    cards = (
        (
            await db.execute(
                select(ActionCard)
                .where(
                    ActionCard.is_active,
                    ActionCard.code.in_(
                        (*CARD_CODES, "purchase") if schema_version == 8 else CARD_CODES
                    ),
                )
                .order_by(ActionCard.id)
            )
        )
        .scalars()
        .all()
    )
    return [card_out(row, schema_version=schema_version) for row in cards]


async def round_cards(db: AsyncSession, round_id: int) -> list[ActionCardOut]:
    row = await get_round(db, round_id)
    specs = load_round_card_specs(row)
    policy = round_policy(row, specs)
    return [
        card_out(
            spec,
            policy.for_card(spec.key),
            schema_version=contract_version(row.game_config),
        )
        for spec in sorted(specs.values(), key=lambda spec: spec.id)
    ]
