"""Participant API: one current game and one final scenario."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.api.deps import (
    CurrentPrincipal,
    get_current_participant,
)
from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.schemas.leaderboard import LeaderboardPageOut, ResultOut
from src.aml_workshop_simulator.schemas.participant_state import ParticipantStateOut
from src.aml_workshop_simulator.schemas.rounds import ActionCardOut, RoundPublicOut
from src.aml_workshop_simulator.schemas.scenarios import (
    ScenarioOut,
    ScenarioPreviewIn,
    ScenarioPreviewOut,
    ScenarioPutIn,
    ScenarioSubmitIn,
)
from src.aml_workshop_simulator.services import participant_state, results, scenarios
from src.aml_workshop_simulator.services.catalog import round_cards

router = APIRouter()


@router.get("/current", response_model=RoundPublicOut | None)
async def current_round(db: AsyncSession = Depends(get_db)):
    return await participant_state.current_round(db)


@router.get("/current/state", response_model=ParticipantStateOut)
async def current_state(
    principal: CurrentPrincipal = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
):
    return await participant_state.read(db, principal.user_id)


@router.get("/{round_id}/cards", response_model=list[ActionCardOut])
async def cards(round_id: int, db: AsyncSession = Depends(get_db)):
    return await round_cards(db, round_id)


@router.get("/{round_id}/scenario", response_model=ScenarioOut | None)
async def scenario(
    round_id: int,
    principal: CurrentPrincipal = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
):
    return await scenarios.read(db, round_id, principal.user_id)


@router.put("/{round_id}/scenario", response_model=ScenarioOut)
async def save_scenario(
    round_id: int,
    payload: ScenarioPutIn,
    principal: CurrentPrincipal = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
):
    return await scenarios.save(db, round_id, principal.user_id, payload)


@router.post("/{round_id}/scenario/preview", response_model=ScenarioPreviewOut)
async def preview_scenario(
    round_id: int,
    payload: ScenarioPreviewIn,
    principal: CurrentPrincipal = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
):
    return await scenarios.preview(db, round_id, principal.user_id, payload)


@router.post("/{round_id}/scenario/submit", response_model=ScenarioOut)
async def submit_scenario(
    round_id: int,
    payload: ScenarioSubmitIn,
    request: Request,
    principal: CurrentPrincipal = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
):
    return await scenarios.submit(
        db, round_id, principal.user_id, payload, request.state.request_id
    )


@router.get("/{round_id}/result", response_model=ResultOut | None)
async def result(
    round_id: int,
    principal: CurrentPrincipal = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
):
    return await results.result(db, round_id, principal.user_id)


@router.get(
    "/{round_id}/leaderboard",
    response_model=LeaderboardPageOut,
)
async def leaderboard(
    round_id: int,
    limit: int = Query(50, ge=1, le=200),
    principal: CurrentPrincipal = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
):
    return await results.public_board(db, round_id, principal.user_id, limit)
