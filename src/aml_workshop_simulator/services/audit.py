"""Append-only audit trail.

One helper, used by both the admin routers and the participant router: an
event is added to the *current* transaction, so it is committed together with
the change it describes or not at all. Nothing here writes personal data — an
event carries identifiers, a reason and safe metadata.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.db.models.audit_events import AuditEvent


async def preserve_game_references(db: AsyncSession, round_id: int, *, editing_only=False):
    """Copy IDs before FK SET NULL; stay in the caller's deletion transaction."""
    await db.execute(text(
        "UPDATE audit_events SET metadata = COALESCE(NULLIF(metadata, 'null'::jsonb), '{}'::jsonb) "
        "|| jsonb_build_object('previous_scenario_id', scenario_id) "
        "WHERE scenario_id IN (SELECT id FROM scenarios WHERE round_id=:rid "
        "AND (NOT :editing_only OR status='editing'))"
    ), {"rid": round_id, "editing_only": editing_only})
    if not editing_only:
        await db.execute(text(
            "UPDATE audit_events SET metadata = COALESCE(NULLIF(metadata, 'null'::jsonb), '{}'::jsonb) "
            "|| jsonb_build_object('previous_round_id', round_id) WHERE round_id=:rid"
        ), {"rid": round_id})


async def record_event(
    db: AsyncSession,
    *,
    actor_user_id: int,
    event_type: str,
    round_id: int | None = None,
    scenario_id: int | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    reason: str | None = None,
    request_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor_user_id=actor_user_id,
            round_id=round_id,
            scenario_id=scenario_id,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            reason=reason,
            request_id=request_id,
            metadata_=metadata,
            created_at=datetime.now(UTC),
        )
    )
