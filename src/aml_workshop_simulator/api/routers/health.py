from __future__ import annotations

from pathlib import Path
from functools import lru_cache

from fastapi import APIRouter, Depends, Response, Request, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.core.config import settings
from src.aml_workshop_simulator.core.version import SERVICE_VERSION
from src.aml_workshop_simulator.domain.rules import RULESET_VERSION
from src.aml_workshop_simulator.domain.scoring import (
    LEADERBOARD_VERSION,
)
from src.aml_workshop_simulator.schemas.health import LiveOut, ReadyOut

from src.aml_workshop_simulator.core.observability import metrics, require_metrics, readiness_failure

router = APIRouter()


@router.get('/internal/metrics', include_in_schema=False)
async def internal_metrics(request: Request):
    from src.aml_workshop_simulator.db.session import pool_metrics
    require_metrics(request, settings.METRICS_TOKEN)
    for key, value in pool_metrics().items():
        metrics.gauge(key, value)
    return metrics.snapshot()


MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "migrations" / "versions"


@lru_cache(maxsize=1)
def _expected_heads() -> frozenset[str]:
    from alembic.script import ScriptDirectory

    return frozenset(ScriptDirectory(str(MIGRATIONS_DIR.parent)).get_heads())


@router.get("/health/live", operation_id="health_live", response_model=LiveOut)
async def health_live() -> dict[str, str]:
    """Liveness only: never touches the database."""
    return {"status": "ok", "service": "api", "version": SERVICE_VERSION, "git_sha": settings.GIT_SHA}


@router.get(
    "/health/ready",
    operation_id="health_ready",
    response_model=ReadyOut,
    responses={503: {"model": ReadyOut, "description": "Сервис не готов"}},
)
async def health_ready(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    from src.aml_workshop_simulator.services.game_classifier import get_game_classifier
    from src.aml_workshop_simulator.core.errors import Conflict

    try:
        scorer = get_game_classifier()
    except Conflict as exc:
        readiness_failure(request.state.request_id, "model", exc)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "not_ready",
            "checks": {"database": "not_checked", "model": {"status": "unavailable"}},
        }
    checks: dict[str, object] = {
        "model": scorer.identity,
        "ruleset_versions": sorted(
            {RULESET_VERSION, scorer.identity["model_version"], LEADERBOARD_VERSION}
        ),
    }
    try:
        # Простейший ping — не полноценный запрос к данным, а проверка, что
        # соединение с Postgres вообще устанавливается и СУБД отвечает.
        await db.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception as exc:
        readiness_failure(request.state.request_id, "database", exc)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "checks": {"database": "unavailable"}}

    try:
        applied = {
            row[0]
            for row in (
                await db.execute(text("SELECT version_num FROM alembic_version"))
            ).all()
        }
    except Exception as exc:
        readiness_failure(request.state.request_id, "migrations", exc)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        checks["migrations"] = "alembic_version missing"
        return {"status": "not_ready", "checks": checks}

    expected = _expected_heads()
    if expected and applied != expected:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        checks["migrations"] = "behind head"
        return {"status": "not_ready", "checks": checks}

    checks["migrations"] = "head"
    from src.aml_workshop_simulator.services.model_scoring import get_round_scorer

    try:
        config = (await db.execute(select(Round.game_config))).scalar_one_or_none()
        if config is not None:
            required = get_round_scorer(config)
            required.check_config(config, require_pin=True)
            checks["round_model"] = {"status": "available"}
    except Exception as exc:
        readiness_failure(request.state.request_id, "round_model", exc)
        # Package paths, database details and exception text are not public health data.
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        checks["round_model"] = {"status": "unavailable"}
        return {"status": "not_ready", "checks": checks}
    return {"status": "ready", "checks": checks}
