from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from datetime import datetime, timezone


class ScenarioRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_and_round(
            self,
            user_id: int,
            round_id: int) -> Scenario | None:
        stmt = select(Scenario).where(
            Scenario.participant_id == user_id,
            Scenario.round_id == round_id
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create_draft(self, user_id: int, round_id: int) -> Scenario:
        scenario = Scenario(
            participant_id=user_id,
            round_id=round_id,
            status="draft",
            steps=[],
            revision=1,
            updated_at=datetime.now(timezone.utc)
        )
        self.session.add(scenario)
        await self.session.commit()
        await self.session.refresh(scenario)
        return scenario

    async def update(self, scenario: Scenario):
        scenario.updated_at = datetime.now(timezone.utc)
        self.session.add(scenario)
        await self.session.commit()
        await self.session.refresh(scenario)
