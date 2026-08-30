"""Participant inspector.

This is the only place where real identities, technical session metadata and
the complete chain of every saved draft are exposed — and only to an
administrator session. Nothing here is reachable from the participant API.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.api.deps import CurrentPrincipal, get_current_admin
from src.aml_workshop_simulator.api.errors import Conflict, Forbidden, NotFound
from src.aml_workshop_simulator.api.pagination import decode_cursor, take_page
from src.aml_workshop_simulator.api.routers.admin.common import audit, get_round
from src.aml_workshop_simulator.db.models.audit_events import AuditEvent
from src.aml_workshop_simulator.db.models.leaderboard_adjustments import (
    LeaderboardAdjustment,
)
from src.aml_workshop_simulator.db.models.scenario_versions import ScenarioVersion
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.db.models.scoring_results import ScoringResult
from src.aml_workshop_simulator.db.models.sessions import Session
from src.aml_workshop_simulator.db.models.users import User
from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.domain.presentation import describe_chain
from src.aml_workshop_simulator.schemas.admin import (
    AccessUpdateIn,
    PlayerDetailOut,
    PlayerDetailUserOut,
    PlayerSummaryOut,
    PlayerSummaryPageOut,
    ScenarioVersionAdminOut,
    SessionInfoOut,
)
from src.aml_workshop_simulator.services.scenario_service import (
    load_round_card_specs,
    round_policy,
)
from src.aml_workshop_simulator.services.scenario_versions import (
    count_versions,
    get_version,
    list_versions,
    version_summary,
)

router = APIRouter()


@router.get(
    "/rounds/{round_id}/participants",
    response_model=PlayerSummaryPageOut,
    operation_id="admin_participants",
)
async def list_participants(
    round_id: int,
    query: str | None = Query(default=None, max_length=320),
    access: str = Query(default="all", pattern="^(all|active|blocked)$"),
    scenario_status: str | None = Query(
        default=None, pattern="^(none|draft|submitted|scored)$"
    ),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None),
    _: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> PlayerSummaryPageOut:
    """One page of the roster, ordered by registration.

    A workshop runs for up to 500 participants, so the roster is paged by
    `User.id` rather than truncated: an organiser who cannot see a participant
    cannot unblock them either.
    """
    await get_round(db, round_id)
    after = decode_cursor(cursor, 1)

    stmt = (
        select(User, Scenario, ScoringResult)
        .outerjoin(
            Scenario,
            (Scenario.participant_id == User.id) & (Scenario.round_id == round_id),
        )
        .outerjoin(ScoringResult, ScoringResult.scenario_id == Scenario.id)
        .where(User.role == "participant")
        .order_by(User.id)
        .limit(limit + 1)
    )
    if after is not None:
        stmt = stmt.where(User.id > int(after[0]))
    if access == "active":
        stmt = stmt.where(User.is_blocked.is_(False))
    elif access == "blocked":
        stmt = stmt.where(User.is_blocked.is_(True))
    if query:
        pattern = f"%{query.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(User.email).like(pattern),
                func.lower(User.display_name).like(pattern),
            )
        )
    # Filtering in SQL and not after the fetch: a page dropped rows in Python
    # returns fewer than `limit` while further matches still exist, which reads
    # as "no more participants".
    if scenario_status == "none":
        stmt = stmt.where(Scenario.id.is_(None))
    elif scenario_status:
        stmt = stmt.where(Scenario.status == scenario_status)

    fetched = (await db.execute(stmt)).all()
    page, next_cursor = take_page(fetched, limit, lambda row: [row[0].id])

    # Draft counts for this page only. Counting every version in the database
    # cost thousands of rows per request for a list of at most 500.
    scenario_ids = [scenario.id for _, scenario, _ in page if scenario is not None]
    version_counts: dict[int, int] = {}
    if scenario_ids:
        version_counts = dict(
            (
                await db.execute(
                    select(ScenarioVersion.scenario_id, func.count(ScenarioVersion.id))
                    .where(ScenarioVersion.scenario_id.in_(scenario_ids))
                    .group_by(ScenarioVersion.scenario_id)
                )
            ).all()
        )

    rows = [
        PlayerSummaryOut(
            id=user.id,
            email=user.email,
            display_name=user.display_name or user.email,
            is_blocked=bool(user.is_blocked),
            access_revision=int(user.access_revision or 1),
            scenario_status=scenario.status if scenario else "none",
            scenario_revision=scenario.revision if scenario else None,
            version_count=version_counts.get(scenario.id, 0) if scenario else 0,
            game_score=str(result.game_score) if result else None,
            risk_label=result.risk_label if result else None,
            registered_at=user.created_at,
            last_login_at=user.last_login_at,
        )
        for user, scenario, result in page
    ]
    return PlayerSummaryPageOut(rows=rows, next_cursor=next_cursor)


def _session_out(row: Session, now: datetime) -> SessionInfoOut:
    expires_at = row.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return SessionInfoOut(
        id=str(row.id),
        audience=str(row.audience),
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        revoke_reason=row.revoke_reason,
        is_active=row.revoked_at is None and expires_at is not None and expires_at > now,
        ip_address=str(row.ip_address) if row.ip_address else None,
        user_agent=row.user_agent,
        accept_language=row.accept_language,
    )


async def _load_user(db: AsyncSession, participant_id: int) -> User:
    user = (
        await db.execute(
            select(User).where(User.id == participant_id, User.role == "participant")
        )
    ).scalars().first()
    if user is None:
        raise NotFound("Участник не найден.", code="participant_not_found")
    return user


@router.get(
    "/rounds/{round_id}/participants/{participant_id}",
    response_model=PlayerDetailOut,
    operation_id="admin_participant_detail",
)
async def participant_detail(
    round_id: int,
    participant_id: int,
    response: Response,
    _: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> PlayerDetailOut:
    await get_round(db, round_id)
    user = await _load_user(db, participant_id)

    scenario = (
        await db.execute(
            select(Scenario).where(
                Scenario.round_id == round_id, Scenario.participant_id == participant_id
            )
        )
    ).scalars().first()

    result_payload: dict[str, Any] | None = None
    versions: list[dict[str, Any]] = []
    if scenario is not None:
        versions = [
            version_summary(
                version,
                is_current=version.id == scenario.current_version_id,
                is_submitted=version.id == scenario.submitted_version_id,
            )
            for version in await list_versions(db, scenario.id)
        ]
        result = (
            await db.execute(
                select(ScoringResult).where(ScoringResult.scenario_id == scenario.id)
            )
        ).scalars().first()
        adjustment = (
            await db.execute(
                select(LeaderboardAdjustment).where(
                    LeaderboardAdjustment.scenario_id == scenario.id
                )
            )
        ).scalars().first()
        if result is not None:
            result_payload = {
                "base": {
                    "risk_score": str(result.risk_score),
                    "risk_label": result.risk_label,
                    "stealth_score": str(result.stealth_score),
                    "resource_score": str(result.resource_score),
                    "game_score": str(result.game_score),
                },
                "effective": {
                    "risk_score": str(
                        adjustment.risk_score_override
                        if adjustment and adjustment.risk_score_override is not None
                        else result.risk_score
                    ),
                    "resource_score": str(
                        adjustment.resource_score_override
                        if adjustment and adjustment.resource_score_override is not None
                        else result.resource_score
                    ),
                    "game_score": str(
                        adjustment.game_score_override
                        if adjustment and adjustment.game_score_override is not None
                        else result.game_score
                    ),
                },
                "explanation": result.explanation or {},
                "adjustment": (
                    {
                        "revision": adjustment.revision,
                        "reason": adjustment.reason,
                        "admin_user_id": adjustment.admin_user_id,
                        "updated_at": adjustment.updated_at.isoformat(),
                    }
                    if adjustment
                    else None
                ),
            }

    now = datetime.now(UTC)
    session_rows = (
        (
            await db.execute(
                select(Session)
                .where(Session.user_id == user.id)
                .order_by(Session.created_at.desc())
                .limit(25)
            )
        )
        .scalars()
        .all()
    )
    sessions = [_session_out(row, now) for row in session_rows]
    total_sessions = int(
        (
            await db.execute(
                select(func.count(Session.id)).where(Session.user_id == user.id)
            )
        ).scalar()
        or 0
    )
    last_with_ip = next((item for item in sessions if item.ip_address), None)

    activity = (
        (
            await db.execute(
                select(AuditEvent)
                .where(AuditEvent.round_id == round_id, AuditEvent.target_id == str(user.id))
                .order_by(AuditEvent.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    response.headers["Cache-Control"] = "no-store"
    return PlayerDetailOut(
        user=PlayerDetailUserOut(
            id=user.id,
            email=user.email,
            display_name=user.display_name or user.email,
            is_blocked=bool(user.is_blocked),
            blocked_reason=user.blocked_reason,
            access_revision=int(user.access_revision or 1),
            created_at=user.created_at,
            first_login_at=user.first_login_at,
            last_login_at=user.last_login_at,
            active_session_count=sum(1 for item in sessions if item.is_active),
            total_session_count=total_sessions,
            last_ip_address=last_with_ip.ip_address if last_with_ip else None,
            last_user_agent=last_with_ip.user_agent if last_with_ip else None,
        ),
        scenario=(
            {
                "id": scenario.id,
                "status": scenario.status,
                "revision": scenario.revision,
                "steps": scenario.steps or [],
                "resources": scenario.resource_snapshot or {},
                "updated_at": scenario.updated_at.isoformat(),
                "submitted_at": (
                    scenario.submitted_at.isoformat() if scenario.submitted_at else None
                ),
                "current_version_id": scenario.current_version_id,
                "submitted_version_id": scenario.submitted_version_id,
                "version_count": await count_versions(db, scenario.id),
            }
            if scenario
            else None
        ),
        versions=versions,
        sessions=sessions,
        result=result_payload,
        recent_activity=[
            {
                "event_type": event.event_type,
                "reason": event.reason,
                "created_at": event.created_at.isoformat(),
            }
            for event in activity
        ],
    )


@router.get(
    "/rounds/{round_id}/participants/{participant_id}/scenario-versions/{revision}",
    response_model=ScenarioVersionAdminOut,
    operation_id="admin_participant_scenario_version",
)
async def participant_scenario_version(
    round_id: int,
    participant_id: int,
    revision: int,
    response: Response,
    _: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ScenarioVersionAdminOut:
    """One saved version with every parameter of every step spelled out.

    Values that happen to equal a default, a `false` or a `0` are part of the
    answer: the inspector must never drop them.
    """
    round_obj = await get_round(db, round_id)
    await _load_user(db, participant_id)
    scenario = (
        await db.execute(
            select(Scenario).where(
                Scenario.round_id == round_id, Scenario.participant_id == participant_id
            )
        )
    ).scalars().first()
    if scenario is None:
        raise NotFound("Сценарий участника не найден.", code="scenario_not_found")
    version = await get_version(db, scenario.id, revision)
    if version is None:
        raise NotFound("Версия черновика не найдена.", code="scenario_version_not_found")

    specs = await load_round_card_specs(db, round_obj)
    policy = round_policy(round_obj, specs)
    steps = list(version.steps or [])
    snapshot = version.resource_snapshot or {}
    response.headers["Cache-Control"] = "no-store"
    summary = version_summary(
        version,
        is_current=version.id == scenario.current_version_id,
        is_submitted=version.id == scenario.submitted_version_id,
    )
    return ScenarioVersionAdminOut(
        id=summary["id"],
        revision=summary["revision"],
        label=summary["label"],
        step_count=summary["step_count"],
        created_at=summary["created_at"],
        created_by_user_id=summary["created_by_user_id"],
        restored_from_revision=summary["restored_from_revision"],
        is_current=summary["is_current"],
        is_submitted=summary["is_submitted"],
        valid=summary["valid"],
        goal_reached=summary["goal_reached"],
        steps=steps,
        described_steps=describe_chain(steps, specs, snapshot, policy),
        resources=snapshot,
    )


@router.put(
    "/rounds/{round_id}/participants/{participant_id}/access",
    response_model=PlayerSummaryOut,
    operation_id="admin_participant_access",
)
async def update_participant_access(
    round_id: int,
    participant_id: int,
    payload: AccessUpdateIn,
    request: Request,
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> PlayerSummaryOut:
    await get_round(db, round_id)
    if participant_id == principal.user_id:
        raise Forbidden("Администратор не может заблокировать сам себя.", code="forbidden")

    user = (
        await db.execute(
            select(User)
            .where(User.id == participant_id, User.role == "participant")
            .with_for_update()
        )
    ).scalars().first()
    if user is None:
        raise NotFound("Участник не найден.", code="participant_not_found")

    if bool(user.is_blocked) == payload.blocked:
        # Idempotent repeat of the same desired state.
        return await player_summary(db, round_id, user)

    if int(user.access_revision or 0) != payload.expected_access_revision:
        raise Conflict(
            "Состояние доступа изменено другим администратором. Обновите список "
            f"(актуальная ревизия {user.access_revision}).",
            code="participant_access_conflict",
            details={"current_access_revision": int(user.access_revision or 0)},
        )

    now = datetime.now(UTC)
    user.is_blocked = payload.blocked
    user.access_revision = int(user.access_revision or 0) + 1
    user.updated_at = now
    if payload.blocked:
        user.blocked_reason = payload.reason
        user.blocked_at = now
        user.blocked_by_user_id = principal.user_id
        # Blocking revokes every active session in the same transaction.
        await db.execute(
            update(Session)
            .where(Session.user_id == user.id, Session.revoked_at.is_(None))
            .values(
                revoked_at=now,
                revoke_reason="account_blocked",
                revoked_by_user_id=principal.user_id,
            )
        )
    else:
        user.blocked_reason = None
        user.blocked_at = None
        user.blocked_by_user_id = None

    await audit(
        db,
        actor_user_id=principal.user_id,
        event_type="participant_blocked" if payload.blocked else "participant_unblocked",
        round_id=round_id,
        target_type="user",
        target_id=str(user.id),
        reason=payload.reason,
        request_id=getattr(request.state, "request_id", None),
        metadata={"access_revision_after": user.access_revision},
    )
    await db.commit()
    await db.refresh(user)
    return await player_summary(db, round_id, user)


async def player_summary(db: AsyncSession, round_id: int, user: User) -> PlayerSummaryOut:
    scenario = (
        await db.execute(
            select(Scenario).where(
                Scenario.round_id == round_id, Scenario.participant_id == user.id
            )
        )
    ).scalars().first()
    result = None
    if scenario is not None:
        result = (
            await db.execute(
                select(ScoringResult).where(ScoringResult.scenario_id == scenario.id)
            )
        ).scalars().first()
    return PlayerSummaryOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name or user.email,
        is_blocked=bool(user.is_blocked),
        access_revision=int(user.access_revision or 1),
        scenario_status=scenario.status if scenario else "none",
        scenario_revision=scenario.revision if scenario else None,
        version_count=await count_versions(db, scenario.id) if scenario else 0,
        game_score=str(result.game_score) if result else None,
        risk_label=result.risk_label if result else None,
        registered_at=user.created_at,
        last_login_at=user.last_login_at,
    )
