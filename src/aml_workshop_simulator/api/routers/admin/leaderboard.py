"""Read-only administrator leaderboard."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.api.deps import get_current_admin
from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.schemas.leaderboard import AdminLeaderboardPageOut
from src.aml_workshop_simulator.services.results import admin_board

router = APIRouter(dependencies=[Depends(get_current_admin)])


@router.get("/rounds/{round_id}/leaderboard", response_model=AdminLeaderboardPageOut)
async def leaderboard(round_id: int, db: AsyncSession = Depends(get_db)):
    return await admin_board(db, round_id)
