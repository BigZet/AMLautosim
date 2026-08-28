from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.domain.rules import RULESET_VERSION
from src.aml_workshop_simulator.domain.scoring import LEADERBOARD_VERSION, SCORING_VERSION

router = APIRouter()

MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "migrations" / "versions"


def _expected_heads() -> set[str]:
    """Revision ids that have no successor inside `migrations/versions`."""
    revisions: dict[str, str | None] = {}
    for path in MIGRATIONS_DIR.glob("*.py"):
        revision: str | None = None
        down: str | None = None
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("revision:") or stripped.startswith("revision ="):
                revision = stripped.split("=", 1)[1].strip().strip("'\"")
            elif stripped.startswith("down_revision"):
                value = stripped.split("=", 1)[1].strip()
                down = None if value == "None" else value.strip("'\"")
            if revision and down is not None:
                break
        if revision:
            revisions[revision] = down
    parents = {value for value in revisions.values() if value}
    return {revision for revision in revisions if revision not in parents}


@router.get("/health/live", operation_id="health_live")
async def health_live() -> dict[str, str]:
    """Liveness only: never touches the database."""
    return {"status": "ok", "service": "api", "version": "1.0.0"}


@router.get("/health/ready", operation_id="health_ready")
async def health_ready(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    checks: dict[str, object] = {
        "ruleset_versions": sorted(
            {RULESET_VERSION, SCORING_VERSION, LEADERBOARD_VERSION}
        )
    }
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "checks": {"database": "unavailable"}}

    try:
        applied = {
            row[0]
            for row in (await db.execute(text("SELECT version_num FROM alembic_version"))).all()
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
