from __future__ import annotations

from fastapi import APIRouter, Depends, status, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.db.session import get_db

router = APIRouter()


@router.get("/health/live")
async def health_live() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "aml_workshop_simulator",
        "version": "1.0.0"}


@router.get("/health/ready")
async def health_ready(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready", "error": str(e)}
