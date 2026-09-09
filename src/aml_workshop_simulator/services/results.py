"""Published results and public/admin projections."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.db.queries import get_round
from src.aml_workshop_simulator.schemas.leaderboard import (
    AdminLeaderboardPageOut,
    AdminLeaderboardRowOut,
    LeaderboardPageOut,
    LeaderboardRowOut,
    ResultOut,
)
from src.aml_workshop_simulator.services import participant_state
from src.aml_workshop_simulator.services.leaderboard_service import build_leaderboard


async def result(
    db: AsyncSession, round_id: int, participant_id: int
) -> ResultOut | None:
    return (await participant_state.read(db, participant_id, round_id)).result


async def public_board(
    db: AsyncSession,
    round_id: int,
    participant_id: int,
    limit: int,
) -> LeaderboardPageOut:
    round_obj = await get_round(db, round_id)
    rows = (
        (await build_leaderboard(db, round_id, current_user_id=participant_id))[:limit]
        if round_obj.status == "completed"
        else []
    )
    return LeaderboardPageOut(
        rows=[LeaderboardRowOut(**row) for row in rows], generated_at=datetime.now(UTC)
    )


async def admin_board(db: AsyncSession, round_id: int) -> AdminLeaderboardPageOut:
    round_obj = await get_round(db, round_id)
    rows = (
        await build_leaderboard(db, round_id, include_blocked=True)
        if round_obj.status == "completed"
        else []
    )
    return AdminLeaderboardPageOut(
        rows=[AdminLeaderboardRowOut(**row) for row in rows],
        generated_at=datetime.now(UTC),
    )
