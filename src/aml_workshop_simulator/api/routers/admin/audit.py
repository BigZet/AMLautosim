from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.api.deps import CurrentPrincipal, get_current_admin
from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.schemas.admin import AuditPageOut
from src.aml_workshop_simulator.services import audit_queries as operations

router = APIRouter()


@router.get(
    "/rounds/{round_id}/audit-events",
    response_model=AuditPageOut,
    operation_id="admin_audit_events",
)
async def audit_events(
    round_id: int,
    event_type: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    _: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AuditPageOut:
    return await operations.audit_events(
        round_id=round_id, event_type=event_type, limit=limit, db=db
    )
