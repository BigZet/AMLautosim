from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.domain.rules import RULESET_VERSION
from src.aml_workshop_simulator.domain.scoring import (
    LEADERBOARD_VERSION,
)
from src.aml_workshop_simulator.schemas.health import LiveOut, ReadyOut

router = APIRouter()

MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "migrations" / "versions"


def _expected_heads() -> set[str]:
    from alembic.script import ScriptDirectory

    return set(ScriptDirectory(str(MIGRATIONS_DIR.parent)).get_heads())


@router.get("/health/live", operation_id="health_live", response_model=LiveOut)
async def health_live() -> dict[str, str]:
    """Liveness only: never touches the database."""
    return {"status": "ok", "service": "api", "version": "2.0.0"}


@router.get(
    "/health/ready",
    operation_id="health_ready",
    response_model=ReadyOut,
    responses={503: {"model": ReadyOut, "description": "Сервис не готов"}},
)
async def health_ready(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    from src.aml_workshop_simulator.services.game_classifier import get_game_classifier
    from src.aml_workshop_simulator.core.errors import Conflict

    try:
        scorer = get_game_classifier()
    except Conflict:
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
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "checks": {"database": "unavailable"}}

    try:
        applied = {
            row[0]
            for row in (
                await db.execute(text("SELECT version_num FROM alembic_version"))
            ).all()
        }
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        checks["migrations"] = "alembic_version missing"
        return {"status": "not_ready", "checks": checks}

    expected = _expected_heads()
    if expected and applied != expected:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        checks["migrations"] = "behind head"
        return {"status": "not_ready", "checks": checks}

    checks["migrations"] = "head"
    return {"status": "ready", "checks": checks}
