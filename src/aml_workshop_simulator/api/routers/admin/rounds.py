"""HTTP commands for the current game."""

from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.api.deps import CurrentPrincipal, get_current_admin
from src.aml_workshop_simulator.db.queries import get_round
from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.schemas.admin import (
    RoundAdminOut,
    RoundCreateIn,
    RoundUpdateIn,
    ScoringSummaryOut,
)
from src.aml_workshop_simulator.schemas.editor_metadata import EditorMetadataOut
from src.aml_workshop_simulator.schemas.round_config import (
    RoundConfigInput,
    parse_game_config,
)
from src.aml_workshop_simulator.core.expanded_game import expanded_game_config
from src.aml_workshop_simulator.services.game_classifier import game_config
from src.aml_workshop_simulator.domain.contract_versions import (
    require_new_round_allowed,
)
from src.aml_workshop_simulator.schemas.rounds import ActionCardOut
from src.aml_workshop_simulator.services import admin_rounds as operations
from src.aml_workshop_simulator.services import scoring_run
from src.aml_workshop_simulator.services.catalog import catalog_cards
from src.aml_workshop_simulator.services.round_configuration import round_out

router = APIRouter(dependencies=[Depends(get_current_admin)])


@router.get("/game-config/default", response_model=RoundConfigInput)
async def default_game_config(
    schema_version: int = Query(default=10, ge=8, le=10),
) -> dict:
    value = expanded_game_config() if schema_version == 8 else game_config()
    if schema_version not in (8, 10):
        from src.aml_workshop_simulator.core.errors import Conflict

        raise Conflict("Unsupported game version", code="round_contract_not_ready")
    require_new_round_allowed(value)
    return parse_game_config(value).dump()


@router.get("/action-cards", response_model=list[ActionCardOut])
async def action_cards(
    schema_version: int = Query(default=10, ge=8, le=10),
    db: AsyncSession = Depends(get_db),
):
    return await catalog_cards(db, schema_version=schema_version)


@router.get("/rounds/current", response_model=RoundAdminOut | None)
async def current_round(db: AsyncSession = Depends(get_db)):
    return await operations.current(db)


@router.post("/rounds", response_model=RoundAdminOut, status_code=201)
async def create_round(
    payload: RoundCreateIn,
    request: Request,
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return await operations.create(
        db, payload, principal.user_id, request.state.request_id
    )


@router.get("/rounds/{round_id}", response_model=RoundAdminOut)
async def round_detail(round_id: int, db: AsyncSession = Depends(get_db)):
    return round_out(await get_round(db, round_id))


@router.put("/rounds/{round_id}", response_model=RoundAdminOut)
async def update_round(
    round_id: int,
    payload: RoundUpdateIn,
    request: Request,
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return await operations.update_config(
        db, round_id, payload, principal.user_id, request.state.request_id
    )


@router.post("/rounds/{round_id}/start", response_model=RoundAdminOut)
async def start_round(
    round_id: int,
    request: Request,
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return await operations.start(
        db, round_id, principal.user_id, request.state.request_id
    )


@router.post("/rounds/{round_id}/score", response_model=ScoringSummaryOut)
async def score_round(
    round_id: int,
    request: Request,
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return await scoring_run.run(
        db, round_id, principal.user_id, request.state.request_id
    )


@router.post(
    "/rounds/{round_id}/restart", response_model=RoundAdminOut, status_code=201
)
async def restart_round(
    round_id: int,
    request: Request,
    schema_version: int = Query(default=10, ge=8, le=10),
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return await operations.restart(
        db, round_id, principal.user_id, request.state.request_id, schema_version
    )


@router.get("/game-config/editor-metadata", response_model=EditorMetadataOut)
async def editor_metadata():
    from src.aml_workshop_simulator.services.editor_metadata import (
        editor_metadata as build,
    )

    return build()
