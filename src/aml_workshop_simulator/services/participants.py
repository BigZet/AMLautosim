"""Administrator access to accounts and submitted scenarios only."""

from datetime import UTC, datetime

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.core.errors import Conflict, Forbidden, NotFound
from src.aml_workshop_simulator.core.principal import CurrentPrincipal
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.db.models.scoring_results import ScoringResult
from src.aml_workshop_simulator.db.models.sessions import Session
from src.aml_workshop_simulator.db.models.users import User
from src.aml_workshop_simulator.db.queries import get_round
from src.aml_workshop_simulator.schemas.admin import (
    AccessUpdateIn,
    PlayerDetailOut,
    PlayerDetailUserOut,
    PlayerSummaryOut,
    PlayerSummaryPageOut,
)
from src.aml_workshop_simulator.services.audit import record_event
from src.aml_workshop_simulator.services.projections import scenario_out
from src.aml_workshop_simulator.services.results import result


def _summary(user, scenario=None, score=None) -> PlayerSummaryOut:
    return PlayerSummaryOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name or user.email,
        is_blocked=user.is_blocked,
        access_revision=user.access_revision,
        scenario_status=scenario.status if scenario else "none",
        game_score=str(score.game_score) if score else None,
        risk_label=score.risk_label if score else None,
        registered_at=user.created_at,
        last_login_at=user.last_login_at,
    )


async def player_summary(
    db: AsyncSession, round_id: int, user: User
) -> PlayerSummaryOut:
    record = (
        await db.execute(
            select(Scenario, ScoringResult)
            .outerjoin(ScoringResult, ScoringResult.scenario_id == Scenario.id)
            .where(
                Scenario.round_id == round_id,
                Scenario.participant_id == user.id,
                Scenario.status.in_(["submitted", "scored"]),
            )
        )
    ).first()
    return _summary(user, *record) if record else _summary(user)


async def list_participants(
    db: AsyncSession, round_id: int, query: str | None, limit: int
) -> PlayerSummaryPageOut:
    await get_round(db, round_id)
    stmt = (
        select(User, Scenario, ScoringResult)
        .outerjoin(
            Scenario,
            (Scenario.participant_id == User.id)
            & (Scenario.round_id == round_id)
            & Scenario.status.in_(["submitted", "scored"]),
        )
        .outerjoin(ScoringResult, ScoringResult.scenario_id == Scenario.id)
        .where(User.role == "participant")
        .order_by(User.id)
        .limit(limit)
    )
    if query:
        stmt = stmt.where(
            or_(User.email.ilike(f"%{query}%"), User.display_name.ilike(f"%{query}%"))
        )
    return PlayerSummaryPageOut(
        rows=[_summary(*row) for row in (await db.execute(stmt)).all()]
    )


async def detail(
    db: AsyncSession, round_id: int, participant_id: int
) -> PlayerDetailOut:
    await get_round(db, round_id)
    user = (
        await db.execute(
            select(User).where(User.id == participant_id, User.role == "participant")
        )
    ).scalar_one_or_none()
    if user is None:
        raise NotFound("Участник не найден.", code="participant_not_found")
    scenario = (
        await db.execute(
            select(Scenario).where(
                Scenario.round_id == round_id,
                Scenario.participant_id == participant_id,
                Scenario.status.in_(["submitted", "scored"]),
            )
        )
    ).scalar_one_or_none()
    scored = await result(db, round_id, participant_id)
    return PlayerDetailOut(
        user=PlayerDetailUserOut(
            **{key: getattr(user, key) for key in PlayerDetailUserOut.model_fields}
        ),
        scenario=scenario_out(scenario).model_dump(mode="json") if scenario else None,
        result=scored.model_dump(mode="json") if scored else None,
    )


async def update_participant_access(
    *,
    round_id: int,
    participant_id: int,
    payload: AccessUpdateIn,
    request_id: str | None,
    principal: CurrentPrincipal,
    db: AsyncSession,
) -> PlayerSummaryOut:
    await get_round(db, round_id, lock="share")
    if participant_id == principal.user_id:
        raise Forbidden(
            "Администратор не может заблокировать сам себя.", code="forbidden"
        )

    user = (
        (
            await db.execute(
                select(User)
                .where(User.id == participant_id, User.role == "participant")
                .with_for_update()
            )
        )
        .scalars()
        .first()
    )
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

    await record_event(
        db,
        actor_user_id=principal.user_id,
        event_type="participant_blocked"
        if payload.blocked
        else "participant_unblocked",
        round_id=round_id,
        target_type="user",
        target_id=str(user.id),
        reason=payload.reason,
        request_id=request_id,
        metadata={"access_revision_after": user.access_revision},
    )
    await db.commit()
    await db.refresh(user)
    return await player_summary(db, round_id, user)
