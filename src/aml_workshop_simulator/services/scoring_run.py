"""Durable admission cutoff and shared atomic publication writer."""

from datetime import UTC, datetime

from sqlalchemy import delete, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.core.errors import Conflict
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.db.queries import get_round
from src.aml_workshop_simulator.domain.contract_versions import (
    require_playable_contract,
)
from src.aml_workshop_simulator.schemas.admin import RoundAdminOut, ScoringSummaryOut
from src.aml_workshop_simulator.services.audit import (
    preserve_game_references,
    record_event,
)
from src.aml_workshop_simulator.services.round_configuration import round_out
from src.aml_workshop_simulator.services.scoring_service import (
    score_round as score_round,
)


def _summary(row: Round) -> ScoringSummaryOut:
    return ScoringSummaryOut(
        round_id=row.id,
        status=row.status,
        completed_at=row.completed_at,
        **row.scoring_summary,
    )


async def close_admission(
    db: AsyncSession, round_id: int, actor_id: int, request_id: str | None
) -> RoundAdminOut:
    """Wait for admitted writes, then permanently close admission in its own commit."""
    row = await get_round(db, round_id, lock="update")
    require_playable_contract(row.game_config)
    if row.status == "draft":
        raise Conflict("Раунд ещё не начат.", code="round_locked")
    if row.status == "active":
        row.status = "closed"
        row.closed_at = datetime.now(UTC)
        await preserve_game_references(db, round_id, editing_only=True)
        removed = await db.execute(
            delete(Scenario).where(
                Scenario.round_id == round_id, Scenario.status == "editing"
            )
        )
        submitted = (
            await db.execute(
                select(func.count())
                .select_from(Scenario)
                .where(Scenario.round_id == round_id, Scenario.status == "submitted")
            )
        ).scalar_one()
        await record_event(
            db,
            actor_user_id=actor_id,
            round_id=round_id,
            event_type="round_closed",
            request_id=request_id,
            metadata={
                "deleted_drafts_count": removed.rowcount,
                "submitted_count": submitted,
            },
        )
    await db.commit()
    return round_out(row)
