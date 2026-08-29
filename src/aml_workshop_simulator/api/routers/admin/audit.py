"""Audit trail of every administrator command."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.api.deps import CurrentPrincipal, get_current_admin
from src.aml_workshop_simulator.api.routers.admin.common import get_round as _get_round
from src.aml_workshop_simulator.db.models.audit_events import AuditEvent
from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.schemas.admin import AuditEventOut, AuditPageOut

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
    await _get_round(db, round_id)
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.round_id == round_id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(limit)
    )
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    events = (await db.execute(stmt)).scalars().all()
    return AuditPageOut(
        rows=[
            AuditEventOut(
                id=event.id,
                actor_user_id=event.actor_user_id,
                round_id=event.round_id,
                scenario_id=event.scenario_id,
                event_type=event.event_type,
                target_type=event.target_type,
                target_id=event.target_id,
                reason=event.reason,
                request_id=event.request_id,
                metadata=event.metadata_,
                created_at=event.created_at,
            )
            for event in events
        ],
        next_cursor=None,
    )
