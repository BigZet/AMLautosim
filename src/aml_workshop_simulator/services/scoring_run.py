"""Durable admission cutoff and retryable scoring for a small workshop."""

import logging
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.core.errors import ApplicationError, Conflict
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.db.queries import get_round
from src.aml_workshop_simulator.domain.contract_versions import (
    require_playable_contract,
)
from src.aml_workshop_simulator.domain.lifecycle import require_round_status
from src.aml_workshop_simulator.schemas.admin import RoundAdminOut, ScoringSummaryOut
from src.aml_workshop_simulator.services.audit import preserve_game_references, record_event
from src.aml_workshop_simulator.services.round_configuration import round_out
from src.aml_workshop_simulator.services.scoring_service import score_round

logger = logging.getLogger(__name__)


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
        await db.execute(
            delete(Scenario).where(
                Scenario.round_id == round_id, Scenario.status == "editing"
            )
        )
        await record_event(
            db,
            actor_user_id=actor_id,
            round_id=round_id,
            event_type="round_closed",
            request_id=request_id,
        )
    await db.commit()
    return round_out(row)


async def run(
    db: AsyncSession, round_id: int, actor_id: int, request_id: str | None
) -> ScoringSummaryOut:
    # This commit cannot be undone by a failed calculation or cancelled request.
    await close_admission(db, round_id, actor_id, request_id)
    row = await get_round(db, round_id, lock="update")
    if row.status == "completed":
        return _summary(row)
    row.status = "scoring"
    row.scoring_started_at = datetime.now(UTC)
    row.scoring_error = None
    await db.commit()

    # Re-read after the commit: another request may have scored or reset the game.
    # A concurrent scorer holds this lock throughout calculation; after a process
    # crash PostgreSQL releases it, so a new request can retry the stored state.
    row = await get_round(db, round_id, lock="update")
    if row.status == "completed":
        return _summary(row)
    require_round_status(row.status, "scoring")
    try:
        # Roll back partial scores without releasing the outer round lock.
        async with db.begin_nested():
            await score_round(db, row, actor_id, request_id)
    except Exception as exc:
        if not isinstance(exc, ApplicationError):
            logger.exception("Scoring failed: round_id=%s request_id=%s", round_id, request_id)
        error = exc if isinstance(exc, ApplicationError) else ApplicationError(
            "Ошибка скоринга. Приём сценариев закрыт; организатор может повторить расчёт.",
            code="scoring_failed", status_code=500,
        )
        row = await get_round(db, round_id, lock="update")
        row.status = "closed"
        row.scoring_error = {"code": error.code, "message": error.message, "request_id": request_id}
        await record_event(
            db,
            actor_user_id=actor_id,
            round_id=round_id,
            event_type="scoring_failed",
            request_id=request_id,
            metadata={"error_type": type(exc).__name__, **row.scoring_error},
        )
        await db.commit()
        if error is exc:
            raise
        raise error from exc
    await db.commit()
    return _summary(row)
