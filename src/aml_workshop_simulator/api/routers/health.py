from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from aml_workshop_simulator.core.logging import log_event
from aml_workshop_simulator.db.session import get_db
from aml_workshop_simulator.domain.rules import RULESET_VERSION
from aml_workshop_simulator.domain.scoring import LEADERBOARD_VERSION, SCORING_VERSION

router = APIRouter()

#: Last readiness answer, so only the *transitions* are logged. Polled every ten
#: seconds by the container healthcheck, this endpoint would otherwise be the
#: only thing in the log.
_last_readiness: str | None = None


def _report(status_value: str, checks: dict[str, object]) -> dict[str, object]:
    global _last_readiness
    if status_value != _last_readiness:
        log_event(
            "readiness_changed",
            level=logging.INFO if status_value == "ready" else logging.ERROR,
            outcome=status_value,
            reason_code=str(checks.get("migrations") or checks.get("database") or "ok"),
        )
        _last_readiness = status_value
    return {"status": status_value, "checks": checks}

ROOT = Path(__file__).resolve().parents[4]


@lru_cache(maxsize=1)
def _expected_heads() -> frozenset[str]:
    """Head revisions, read the way Alembic itself reads them.

    Parsing the files by hand meant a missing or moved directory produced an
    empty set, and an empty set silently passed the comparison below: readiness
    reported "head" having verified nothing at all. Alembic raises instead, and
    an unverifiable migration state must fail the check.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return frozenset(ScriptDirectory.from_config(config).get_heads())


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
        return _report("not_ready", {"database": "unavailable"})

    try:
        applied = {
            row[0]
            for row in (await db.execute(text("SELECT version_num FROM alembic_version"))).all()
        }
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        checks["migrations"] = "alembic_version missing"
        return _report("not_ready", checks)

    try:
        expected = _expected_heads()
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        checks["migrations"] = "revision history unreadable"
        return _report("not_ready", checks)

    if applied != expected:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        checks["migrations"] = "behind head"
        return _report("not_ready", checks)

    checks["migrations"] = "head"
    return _report("ready", checks)
