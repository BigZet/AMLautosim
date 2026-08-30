"""Audit trail of every administrator command."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.api.deps import CurrentPrincipal, get_current_admin
from src.aml_workshop_simulator.api.pagination import decode_cursor, take_page
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
    cursor: str | None = Query(default=None),
    _: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AuditPageOut:
    await _get_round(db, round_id)
    after = decode_cursor(cursor, 2)
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.round_id == round_id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(limit + 1)
    )
    if after is not None:
        # The trail is append-only and read newest first, so paging by the
        # timestamp of the last row seen never repeats or skips an event.
        stmt = stmt.where(
            tuple_(AuditEvent.created_at, AuditEvent.id)
            < (datetime.fromisoformat(str(after[0])), int(after[1]))
        )
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    fetched = list((await db.execute(stmt)).scalars().all())
    events, next_cursor = take_page(
        fetched, limit, lambda event: [event.created_at, event.id]
    )
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
        next_cursor=next_cursor,
    )
