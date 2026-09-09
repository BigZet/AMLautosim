"""Account management and submitted scenario inspection."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.api.deps import CurrentPrincipal, get_current_admin
from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.schemas.admin import (
    AccessUpdateIn,
    PlayerDetailOut,
    PlayerSummaryOut,
    PlayerSummaryPageOut,
)
from src.aml_workshop_simulator.services import participants

router = APIRouter(dependencies=[Depends(get_current_admin)])


@router.get("/rounds/{round_id}/participants", response_model=PlayerSummaryPageOut)
async def list_participants(
    round_id: int,
    query: str | None = Query(None, max_length=320),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    return await participants.list_participants(db, round_id, query, limit)


@router.get(
    "/rounds/{round_id}/participants/{participant_id}", response_model=PlayerDetailOut
)
async def participant_detail(
    round_id: int, participant_id: int, db: AsyncSession = Depends(get_db)
):
    return await participants.detail(db, round_id, participant_id)


@router.put(
    "/rounds/{round_id}/participants/{participant_id}/access",
    response_model=PlayerSummaryOut,
)
async def update_access(
    round_id: int,
    participant_id: int,
    payload: AccessUpdateIn,
    request: Request,
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return await participants.update_participant_access(
        round_id=round_id,
        participant_id=participant_id,
        payload=payload,
        request_id=request.state.request_id,
        principal=principal,
        db=db,
    )
