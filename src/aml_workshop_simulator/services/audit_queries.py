"""Application operations for audit queries."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.db.models.audit_events import AuditEvent
from src.aml_workshop_simulator.db.queries import get_round as _get_round
from src.aml_workshop_simulator.schemas.admin import AuditEventOut, AuditPageOut


async def audit_events(
    *, round_id: int, event_type: str | None, limit: int, db: AsyncSession
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
    )
