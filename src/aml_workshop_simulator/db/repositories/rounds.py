from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.db.models.action_cards import ActionCard


class RoundRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active_round(self) -> Round | None:
        stmt = select(Round).where(Round.status == "active")
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_action_cards(self) -> list[ActionCard]:
        stmt = select(ActionCard).where(ActionCard.is_active)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
