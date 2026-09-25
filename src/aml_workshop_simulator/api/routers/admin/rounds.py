"""HTTP commands for the current game."""

import asyncio
import time
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.api.deps import CurrentPrincipal, get_current_admin
from src.aml_workshop_simulator.db.queries import get_round
from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.schemas.admin import (
    RoundAdminOut,
    RoundCreateIn,
    RoundUpdateIn,
    ScoringSummaryOut,
    AdmissionCountsOut,
    ScoringJobOut,
)
from src.aml_workshop_simulator.schemas.editor_metadata import EditorMetadataOut
from src.aml_workshop_simulator.schemas.game_version import GameVersion
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
from src.aml_workshop_simulator.services import scoring_jobs
from src.aml_workshop_simulator.core.errors import ApplicationError, Conflict
from src.aml_workshop_simulator.services.catalog import catalog_cards
from src.aml_workshop_simulator.services.round_configuration import round_out

router = APIRouter(dependencies=[Depends(get_current_admin)])


@router.get("/game-config/default", response_model=RoundConfigInput)
async def default_game_config(
    schema_version: GameVersion = Query(default=GameVersion.current),
) -> dict:
    value = expanded_game_config() if schema_version == 8 else game_config()
    require_new_round_allowed(value)
    return parse_game_config(value).dump()


@router.get("/action-cards", response_model=list[ActionCardOut])
async def action_cards(
    schema_version: GameVersion = Query(default=GameVersion.current),
    db: AsyncSession = Depends(get_db),
):
    return await catalog_cards(db, schema_version=int(schema_version))


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


@router.post(
    "/rounds/{round_id}/score",
    response_model=ScoringJobOut | ScoringSummaryOut,
    status_code=202,
)
async def score_round(
    round_id: int,
    request: Request,
    response: Response,
    wait: bool = False,
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    job = await scoring_jobs.enqueue(
        db, round_id, principal.user_id, request.state.request_id
    )
    if wait:
        # Transitional long-poll only: calculation always belongs to the worker.
        deadline = time.monotonic() + 30
        while True:
            if job.state == "completed" and job.summary is not None:
                response.status_code = 200
                return job.summary
            if job.state == "failed":
                error = job.error or {}
                raise ApplicationError(
                    error.get("message", "Ошибка расчёта."),
                    code=error.get("code", "scoring_failed"),
                    status_code=error.get("status_code", 500),
                )
            if job.state == "cancelled":
                raise Conflict(
                    "Расчёт отменён перезапуском игры.", code="scoring_cancelled"
                )
            if time.monotonic() >= deadline:
                break
            await db.rollback()  # never reserve a pool connection while waiting
            await asyncio.sleep(0.1)
            job = await scoring_jobs.read(db, job.job_id)
    return job


@router.get("/scoring-jobs/{job_id}", response_model=ScoringJobOut)
async def scoring_job(job_id: UUID, db: AsyncSession = Depends(get_db)):
    return await scoring_jobs.read(db, job_id)


@router.get("/rounds/{round_id}/admission", response_model=AdmissionCountsOut)
async def admission_counts(round_id: int, db: AsyncSession = Depends(get_db)):
    return await operations.admission_counts(db, round_id)


@router.post(
    "/rounds/{round_id}/restart", response_model=RoundAdminOut, status_code=201
)
async def restart_round(
    round_id: int,
    request: Request,
    schema_version: GameVersion = Query(default=GameVersion.current),
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    return await operations.restart(
        db, round_id, principal.user_id, request.state.request_id, int(schema_version)
    )


@router.get("/game-config/editor-metadata", response_model=EditorMetadataOut)
async def editor_metadata():
    from src.aml_workshop_simulator.services.editor_metadata import (
        editor_metadata as build,
    )

    return build()
