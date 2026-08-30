"""Append-only audit trail.

One helper, used by both the admin routers and the participant router: an
event is added to the *current* transaction, so it is committed together with
the change it describes or not at all. Nothing here writes personal data — an
event carries identifiers, a reason and safe metadata.

The same call also emits the structured log line `docs/operations.md` §7 asks
for. Doing it here rather than at each of the fifteen call sites is what keeps
the two trails from drifting apart: an action that is audited is logged, with
the same identifiers. The operator-written `reason` stays out of the log — the
audit table is access-controlled, the log stream is not.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.core.logging import log_event
from src.aml_workshop_simulator.db.models.audit_events import AuditEvent


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
    idempotency_key_hash: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    log_event(
        event_type,
        round_id=round_id,
        scenario_id=scenario_id,
        user_id=actor_user_id,
        target_user_id=int(target_id) if target_type == "user" and target_id else None,
    )
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
            idempotency_key_hash=idempotency_key_hash,
            metadata_=metadata,
            created_at=datetime.now(UTC),
        )
    )
