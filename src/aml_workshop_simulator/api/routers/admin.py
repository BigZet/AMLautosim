from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.api.deps import CurrentPrincipal, get_current_admin
from src.aml_workshop_simulator.api.errors import (
    ApiError,
    Conflict,
    Forbidden,
    NotFound,
    ValidationFailed,
)
from src.aml_workshop_simulator.api.routers.rounds import card_out
from src.aml_workshop_simulator.core.security import hash_idempotency_key
from src.aml_workshop_simulator.db.models.action_cards import ActionCard
from src.aml_workshop_simulator.db.models.audit_events import AuditEvent
from src.aml_workshop_simulator.db.models.leaderboard_adjustments import (
    LeaderboardAdjustment,
)
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.db.models.scoring_results import ScoringResult
from src.aml_workshop_simulator.db.models.sessions import Session
from src.aml_workshop_simulator.db.models.users import User
from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.domain.rules import RULESET_VERSION
from src.aml_workshop_simulator.domain.scoring import (
    LEADERBOARD_VERSION,
    SCORING_VERSION,
    weights_sum_to_one,
)
from src.aml_workshop_simulator.schemas.admin import (
    AccessUpdateIn,
    AuditEventOut,
    AuditPageOut,
    LeaderboardAdjustmentIn,
    LeaderboardAdjustmentOut,
    PlayerDetailOut,
    PlayerDetailUserOut,
    PlayerSummaryOut,
    PlayerSummaryPageOut,
    RoundAdminOut,
    RoundCreateIn,
    RoundStatsOut,
    RoundUpdateIn,
    ScoringSummaryOut,
)
from src.aml_workshop_simulator.schemas.leaderboard import (
    AdminLeaderboardPageOut,
    AdminLeaderboardRowOut,
)
from src.aml_workshop_simulator.schemas.rounds import ActionCardOut
from src.aml_workshop_simulator.services.leaderboard_service import (
    build_admin_leaderboard,
)
from src.aml_workshop_simulator.services.scoring_service import NoSubmissions, score_round

router = APIRouter()

SUPPORTED_RULESETS = {RULESET_VERSION}
SUPPORTED_SCORING = {SCORING_VERSION}
SUPPORTED_LEADERBOARD = {LEADERBOARD_VERSION}


def round_out(round_obj: Round) -> RoundAdminOut:
    return RoundAdminOut(
        id=round_obj.id,
        title=round_obj.title,
        status=round_obj.status,
        config_revision=round_obj.config_revision,
        game_config=round_obj.game_config or {},
        scoring_summary=round_obj.scoring_summary,
        created_at=round_obj.created_at,
        activated_at=round_obj.activated_at,
        completed_at=round_obj.completed_at,
    )


def config_version(game_config: dict[str, Any]) -> str:
    payload = {key: value for key, value in game_config.items() if key != "config_version"}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"round-config-v2:sha256:{hashlib.sha256(blob.encode('utf-8')).hexdigest()}"


async def _get_round(db: AsyncSession, round_id: int) -> Round:
    round_obj = (
        await db.execute(select(Round).where(Round.id == round_id))
    ).scalars().first()
    if round_obj is None:
        raise NotFound("Раунд не найден.", code="round_not_found")
    return round_obj


async def _audit(
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


# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------


@router.get(
    "/action-cards",
    response_model=list[ActionCardOut],
    operation_id="admin_action_cards",
)
async def list_action_cards(
    include_inactive: bool = Query(default=False),
    _: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[ActionCardOut]:
    stmt = select(ActionCard).order_by(ActionCard.id)
    if not include_inactive:
        stmt = stmt.where(ActionCard.is_active)
    rows = (await db.execute(stmt)).scalars().all()
    return [card_out(row) for row in rows]


# --------------------------------------------------------------------------
# Rounds
# --------------------------------------------------------------------------


def _validate_game_config(db_cards: list[ActionCard], game_config: dict[str, Any]) -> None:
    ruleset = game_config.get("ruleset_version")
    if ruleset not in SUPPORTED_RULESETS:
        raise Conflict(
            f"Версия правил «{ruleset}» отсутствует в этой сборке. "
            f"Доступны: {', '.join(sorted(SUPPORTED_RULESETS))}.",
            code="round_configuration_invalid",
        )
    scoring_version = (game_config.get("scoring") or {}).get("version")
    if scoring_version not in SUPPORTED_SCORING:
        raise Conflict(
            f"Версия скоринга «{scoring_version}» отсутствует в этой сборке.",
            code="round_configuration_invalid",
        )
    board_version = (game_config.get("leaderboard") or {}).get("version")
    if board_version not in SUPPORTED_LEADERBOARD:
        raise Conflict(
            f"Версия лидерборда «{board_version}» отсутствует в этой сборке.",
            code="round_configuration_invalid",
        )
    if not weights_sum_to_one(game_config):
        raise Conflict(
            "Веса лидерборда должны в сумме давать 1.",
            code="round_configuration_invalid",
        )
    refs = game_config.get("card_versions") or []
    if not refs:
        raise Conflict(
            "Не указан ни один card_version для раунда.",
            code="round_configuration_invalid",
        )
    available = {(card.code, card.version): card for card in db_cards if card.is_active}
    for ref in refs:
        key = (str(ref.get("code")), int(ref.get("version", 0)))
        card = available.get(key)
        if card is None:
            raise Conflict(
                f"Карточка «{key[0]}» версии {key[1]} не найдена или неактивна.",
                code="round_configuration_invalid",
            )
        if int(ref.get("id", card.id)) != card.id:
            raise Conflict(
                f"Идентификатор карточки «{key[0]}» не совпадает с каталогом.",
                code="round_configuration_invalid",
            )


@router.post(
    "/rounds",
    response_model=RoundAdminOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="admin_round_create",
)
async def create_round(
    payload: RoundCreateIn,
    request: Request,
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> RoundAdminOut:
    now = datetime.now(UTC)
    round_obj = Round(
        title=payload.title,
        status="draft",
        config_revision=1,
        game_config=payload.game_config,
        created_by_user_id=principal.user_id,
        created_at=now,
    )
    db.add(round_obj)
    await db.flush()
    await _audit(
        db,
        actor_user_id=principal.user_id,
        event_type="round_created",
        round_id=round_obj.id,
        target_type="round",
        target_id=str(round_obj.id),
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()
    await db.refresh(round_obj)
    return round_out(round_obj)


@router.get(
    "/rounds", response_model=list[RoundAdminOut], operation_id="admin_round_list"
)
async def list_rounds(
    _: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[RoundAdminOut]:
    rounds = (
        (await db.execute(select(Round).order_by(Round.id.desc()))).scalars().all()
    )
    return [round_out(item) for item in rounds]


@router.get(
    "/rounds/{round_id}", response_model=RoundAdminOut, operation_id="admin_round_get"
)
async def get_round(
    round_id: int,
    _: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> RoundAdminOut:
    return round_out(await _get_round(db, round_id))


@router.put(
    "/rounds/{round_id}", response_model=RoundAdminOut, operation_id="admin_round_update"
)
async def update_round(
    round_id: int,
    payload: RoundUpdateIn,
    request: Request,
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> RoundAdminOut:
    round_obj = await _get_round(db, round_id)
    if round_obj.status != "draft":
        raise Conflict(
            "Конфигурация активированного раунда неизменяема.",
            code="round_config_locked",
        )
    if round_obj.config_revision != payload.expected_config_revision:
        raise Conflict(
            "Конфигурация изменена другим администратором. Перезагрузите форму "
            f"(актуальная ревизия {round_obj.config_revision}).",
            code="round_config_conflict",
            details={"current_config_revision": round_obj.config_revision},
        )
    if payload.title is not None:
        round_obj.title = payload.title
    if payload.game_config is not None:
        round_obj.game_config = payload.game_config
    round_obj.config_revision += 1
    await _audit(
        db,
        actor_user_id=principal.user_id,
        event_type="round_updated",
        round_id=round_obj.id,
        target_type="round",
        target_id=str(round_obj.id),
        request_id=getattr(request.state, "request_id", None),
        metadata={"config_revision_after": round_obj.config_revision},
    )
    await db.commit()
    await db.refresh(round_obj)
    return round_out(round_obj)


@router.post(
    "/rounds/{round_id}/activate",
    response_model=RoundAdminOut,
    operation_id="admin_round_activate",
)
async def activate_round(
    round_id: int,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> RoundAdminOut:
    round_obj = await _get_round(db, round_id)
    if round_obj.status == "active":
        return round_out(round_obj)
    if round_obj.status in {"scoring", "completed"}:
        raise Conflict(
            "Раунд уже завершен и не может быть активирован повторно.",
            code="round_locked",
        )

    other = (
        await db.execute(
            select(Round).where(Round.status.in_(["active", "scoring"]), Round.id != round_id)
        )
    ).scalars().first()
    if other is not None:
        raise Conflict(
            f"Уже есть активный раунд #{other.id}. Завершите его перед активацией нового.",
            code="active_round_exists",
            details={"active_round_id": other.id},
        )

    cards = (await db.execute(select(ActionCard))).scalars().all()
    game_config = dict(round_obj.game_config or {})
    _validate_game_config(cards, game_config)
    game_config["config_version"] = config_version(game_config)

    now = datetime.now(UTC)
    round_obj.game_config = game_config
    round_obj.status = "active"
    round_obj.activated_at = now
    await _audit(
        db,
        actor_user_id=principal.user_id,
        event_type="round_activated",
        round_id=round_obj.id,
        target_type="round",
        target_id=str(round_obj.id),
        request_id=getattr(request.state, "request_id", None),
        idempotency_key_hash=(
            hash_idempotency_key(idempotency_key) if idempotency_key else None
        ),
        metadata={"config_version": game_config["config_version"]},
    )
    try:
        await db.commit()
    except IntegrityError as exc:  # partial unique index on active/scoring rounds
        await db.rollback()
        raise Conflict(
            "Другой раунд уже активен.", code="active_round_exists"
        ) from exc
    await db.refresh(round_obj)
    return round_out(round_obj)


@router.post(
    "/rounds/{round_id}/score",
    response_model=ScoringSummaryOut,
    operation_id="admin_round_score",
)
async def trigger_scoring(
    round_id: int,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ScoringSummaryOut:
    round_obj = await _get_round(db, round_id)

    if round_obj.status == "completed" and round_obj.scoring_summary:
        summary = round_obj.scoring_summary
        return ScoringSummaryOut(
            round_id=round_obj.id,
            status=round_obj.status,
            submitted_count=summary.get("submitted_count", 0),
            scored_count=summary.get("scored_count", 0),
            excluded_draft_count=summary.get("excluded_draft_count", 0),
            duration_ms=summary.get("duration_ms", 0),
            scoring_version=summary.get("scoring_version", SCORING_VERSION),
            leaderboard_version=summary.get("leaderboard_version", LEADERBOARD_VERSION),
            completed_at=round_obj.completed_at or datetime.now(UTC),
        )

    if round_obj.status != "active":
        raise Conflict("Скоринг доступен только для активного раунда.", code="round_locked")

    # Serialise concurrent score commands without waiting on a long lock.
    try:
        locked = (
            await db.execute(
                select(Round).where(Round.id == round_id).with_for_update(nowait=True)
            )
        ).scalars().first()
    except DBAPIError as exc:
        await db.rollback()
        raise Conflict(
            "Скоринг уже выполняется другим администратором.",
            code="scoring_in_progress",
        ) from exc
    if locked is None:
        raise NotFound("Раунд не найден.", code="round_not_found")

    try:
        summary = await score_round(
            db,
            locked,
            actor_user_id=principal.user_id,
            request_id=getattr(request.state, "request_id", None),
            idempotency_key_hash=(
                hash_idempotency_key(idempotency_key) if idempotency_key else None
            ),
        )
    except NoSubmissions as exc:
        await db.rollback()
        raise ApiError(
            "В раунде нет отправленных сценариев для скоринга.",
            code="no_submissions",
            status_code=status.HTTP_400_BAD_REQUEST,
        ) from exc
    except Exception:
        await db.rollback()
        raise

    await db.commit()
    await db.refresh(locked)
    return ScoringSummaryOut(
        round_id=locked.id,
        status=locked.status,
        submitted_count=summary["submitted_count"],
        scored_count=summary["scored_count"],
        excluded_draft_count=summary["excluded_draft_count"],
        duration_ms=summary["duration_ms"],
        scoring_version=summary["scoring_version"],
        leaderboard_version=summary["leaderboard_version"],
        completed_at=locked.completed_at or datetime.now(UTC),
    )


@router.get(
    "/rounds/{round_id}/stats",
    response_model=RoundStatsOut,
    operation_id="admin_round_stats",
)
async def round_stats(
    round_id: int,
    _: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> RoundStatsOut:
    await _get_round(db, round_id)

    async def count(stmt: Any) -> int:
        return int((await db.execute(stmt)).scalar() or 0)

    registered = await count(
        select(func.count(User.id)).where(User.role == "participant")
    )
    blocked = await count(
        select(func.count(User.id)).where(User.role == "participant", User.is_blocked)
    )
    drafts = await count(
        select(func.count(Scenario.id)).where(
            Scenario.round_id == round_id, Scenario.status == "draft"
        )
    )
    submitted = await count(
        select(func.count(Scenario.id)).where(
            Scenario.round_id == round_id, Scenario.status == "submitted"
        )
    )
    scored = await count(
        select(func.count(Scenario.id)).where(
            Scenario.round_id == round_id, Scenario.status == "scored"
        )
    )
    public_rows = await count(
        select(func.count(ScoringResult.id))
        .select_from(ScoringResult)
        .join(Scenario, Scenario.id == ScoringResult.scenario_id)
        .join(User, User.id == Scenario.participant_id)
        .where(Scenario.round_id == round_id, User.is_blocked.is_(False))
    )
    last_update = (
        await db.execute(
            select(func.max(Scenario.updated_at)).where(Scenario.round_id == round_id)
        )
    ).scalar()

    return RoundStatsOut(
        registered_users=registered,
        active_users=registered - blocked,
        blocked_users=blocked,
        without_scenario=max(0, registered - (drafts + submitted + scored)),
        draft_scenarios=drafts,
        submitted_scenarios=submitted,
        scored_scenarios=scored,
        public_leaderboard_rows=public_rows,
        last_scenario_update_at=last_update,
    )


# --------------------------------------------------------------------------
# Participants
# --------------------------------------------------------------------------


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
    limit: int = Query(default=100, ge=1, le=100),
    _: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> PlayerSummaryPageOut:
    await _get_round(db, round_id)
    stmt = (
        select(User, Scenario, ScoringResult)
        .outerjoin(
            Scenario,
            (Scenario.participant_id == User.id) & (Scenario.round_id == round_id),
        )
        .outerjoin(ScoringResult, ScoringResult.scenario_id == Scenario.id)
        .where(User.role == "participant")
        .order_by(User.id)
    )
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

    rows: list[PlayerSummaryOut] = []
    for user, scenario, result in (await db.execute(stmt)).all():
        status_value = scenario.status if scenario else "none"
        if scenario_status and status_value != scenario_status:
            continue
        rows.append(
            PlayerSummaryOut(
                id=user.id,
                email=user.email,
                display_name=user.display_name or user.email,
                is_blocked=bool(user.is_blocked),
                access_revision=int(user.access_revision or 1),
                scenario_status=status_value,
                scenario_revision=scenario.revision if scenario else None,
                game_score=str(result.game_score) if result else None,
                risk_label=result.risk_label if result else None,
                last_login_at=user.last_login_at,
            )
        )
        if len(rows) >= limit:
            break
    return PlayerSummaryPageOut(rows=rows, next_cursor=None)


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
    await _get_round(db, round_id)
    user = (
        await db.execute(
            select(User).where(User.id == participant_id, User.role == "participant")
        )
    ).scalars().first()
    if user is None:
        raise NotFound("Участник не найден.", code="participant_not_found")

    scenario = (
        await db.execute(
            select(Scenario).where(
                Scenario.round_id == round_id, Scenario.participant_id == participant_id
            )
        )
    ).scalars().first()

    result_payload: dict[str, Any] | None = None
    if scenario is not None:
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
            last_login_at=user.last_login_at,
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
            }
            if scenario
            else None
        ),
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
    await _get_round(db, round_id)
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
        return await _player_summary(db, round_id, user)

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
            .values(revoked_at=now, revoke_reason="account_blocked",
                    revoked_by_user_id=principal.user_id)
        )
    else:
        user.blocked_reason = None
        user.blocked_at = None
        user.blocked_by_user_id = None

    await _audit(
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
    return await _player_summary(db, round_id, user)


async def _player_summary(db: AsyncSession, round_id: int, user: User) -> PlayerSummaryOut:
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
        game_score=str(result.game_score) if result else None,
        risk_label=result.risk_label if result else None,
        last_login_at=user.last_login_at,
    )


# --------------------------------------------------------------------------
# Leaderboard adjustments
# --------------------------------------------------------------------------


async def _load_result(
    db: AsyncSession, round_id: int, participant_id: int
) -> tuple[Scenario, ScoringResult]:
    scenario = (
        await db.execute(
            select(Scenario).where(
                Scenario.round_id == round_id, Scenario.participant_id == participant_id
            )
        )
    ).scalars().first()
    if scenario is None:
        raise NotFound("Сценарий участника не найден.", code="scenario_not_found")
    result = (
        await db.execute(
            select(ScoringResult).where(ScoringResult.scenario_id == scenario.id)
        )
    ).scalars().first()
    if result is None:
        raise Conflict(
            "Результат еще не рассчитан: сначала выполните скоринг раунда.",
            code="result_not_available",
        )
    return scenario, result


@router.put(
    "/rounds/{round_id}/participants/{participant_id}/leaderboard-adjustment",
    response_model=LeaderboardAdjustmentOut,
    operation_id="admin_adjustment_put",
)
async def upsert_adjustment(
    round_id: int,
    participant_id: int,
    payload: LeaderboardAdjustmentIn,
    request: Request,
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> LeaderboardAdjustmentOut:
    await _get_round(db, round_id)
    overrides = (
        payload.risk_score_override,
        payload.resource_score_override,
        payload.game_score_override,
    )
    if all(value is None for value in overrides):
        raise ValidationFailed(
            "Укажите хотя бы одно значение корректировки.",
            details={
                "violations": [
                    {
                        "field": "game_score_override",
                        "reason": "no_override_provided",
                        "message": "Заполните минимум одно поле корректировки.",
                    }
                ]
            },
        )

    scenario, result = await _load_result(db, round_id, participant_id)
    adjustment = (
        await db.execute(
            select(LeaderboardAdjustment)
            .where(LeaderboardAdjustment.scenario_id == scenario.id)
            .with_for_update()
        )
    ).scalars().first()
    current_revision = adjustment.revision if adjustment else 0
    if current_revision != payload.expected_revision:
        raise Conflict(
            "Корректировка изменена другим администратором "
            f"(актуальная ревизия {current_revision}).",
            code="adjustment_revision_conflict",
            details={"current_revision": current_revision},
        )

    now = datetime.now(UTC)
    before = {
        "game_score": str(
            adjustment.game_score_override if adjustment else result.game_score
        )
    }
    if adjustment is None:
        adjustment = LeaderboardAdjustment(
            scenario_id=scenario.id,
            admin_user_id=principal.user_id,
            revision=1,
            reason=payload.reason,
            updated_at=now,
        )
        db.add(adjustment)
    else:
        adjustment.revision += 1
        adjustment.admin_user_id = principal.user_id
        adjustment.reason = payload.reason
        adjustment.updated_at = now

    adjustment.risk_score_override = payload.risk_score_override
    adjustment.resource_score_override = payload.resource_score_override
    adjustment.game_score_override = payload.game_score_override

    await _audit(
        db,
        actor_user_id=principal.user_id,
        event_type="leaderboard_adjusted",
        round_id=round_id,
        scenario_id=scenario.id,
        target_type="user",
        target_id=str(participant_id),
        reason=payload.reason,
        request_id=getattr(request.state, "request_id", None),
        metadata={
            "revision_before": current_revision,
            "revision_after": adjustment.revision,
            "game_score_before": before["game_score"],
            "game_score_after": str(
                payload.game_score_override
                if payload.game_score_override is not None
                else result.game_score
            ),
        },
    )
    await db.commit()
    await db.refresh(adjustment)

    def effective(override: Decimal | None, base: Any) -> str:
        return str(override if override is not None else base)

    return LeaderboardAdjustmentOut(
        scenario_id=scenario.id,
        revision=adjustment.revision,
        base={
            "risk_score": str(result.risk_score),
            "resource_score": str(result.resource_score),
            "game_score": str(result.game_score),
        },
        effective={
            "risk_score": effective(adjustment.risk_score_override, result.risk_score),
            "resource_score": effective(
                adjustment.resource_score_override, result.resource_score
            ),
            "game_score": effective(adjustment.game_score_override, result.game_score),
        },
        reason=adjustment.reason,
        admin_user_id=adjustment.admin_user_id,
        updated_at=adjustment.updated_at,
    )


@router.delete(
    "/rounds/{round_id}/participants/{participant_id}/leaderboard-adjustment",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="admin_adjustment_delete",
)
async def clear_adjustment(
    round_id: int,
    participant_id: int,
    request: Request,
    expected_revision: int = Query(ge=0),
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _get_round(db, round_id)
    scenario, _result = await _load_result(db, round_id, participant_id)
    adjustment = (
        await db.execute(
            select(LeaderboardAdjustment)
            .where(LeaderboardAdjustment.scenario_id == scenario.id)
            .with_for_update()
        )
    ).scalars().first()
    if adjustment is None:
        return
    if adjustment.revision != expected_revision:
        raise Conflict(
            "Корректировка изменена другим администратором "
            f"(актуальная ревизия {adjustment.revision}).",
            code="adjustment_revision_conflict",
            details={"current_revision": adjustment.revision},
        )
    await _audit(
        db,
        actor_user_id=principal.user_id,
        event_type="leaderboard_adjustment_cleared",
        round_id=round_id,
        scenario_id=scenario.id,
        target_type="user",
        target_id=str(participant_id),
        reason=adjustment.reason,
        request_id=getattr(request.state, "request_id", None),
        metadata={
            "revision_before": adjustment.revision,
            "game_score_before": str(adjustment.game_score_override),
        },
    )
    await db.delete(adjustment)
    await db.commit()


@router.get(
    "/rounds/{round_id}/leaderboard",
    response_model=AdminLeaderboardPageOut,
    operation_id="admin_leaderboard",
)
async def admin_leaderboard(
    round_id: int,
    _: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminLeaderboardPageOut:
    await _get_round(db, round_id)
    rows = await build_admin_leaderboard(db, round_id)
    return AdminLeaderboardPageOut(
        rows=[
            AdminLeaderboardRowOut(
                rank=row["rank"],
                participant_id=row["participant_id"],
                display_name=row["display_name"],
                email=row["email"],
                scenario_id=row["scenario_id"],
                is_blocked=row["is_blocked"],
                base_game_score=f"{row['base_game_score']:.2f}",
                effective_game_score=f"{row['effective_game_score']:.2f}",
                base_risk_score=f"{row['base_risk_score']:.2f}",
                effective_risk_score=f"{row['effective_risk_score']:.2f}",
                base_resource_score=f"{row['base_resource_score']:.2f}",
                effective_resource_score=f"{row['effective_resource_score']:.2f}",
                stealth_score=f"{row['stealth_score']:.2f}",
                risk_label=row["risk_label"],
                is_adjusted=row["is_adjusted"],
                adjustment_reason=row["adjustment_reason"],
            )
            for row in rows
        ],
        next_cursor=None,
        generated_at=datetime.now(UTC),
    )


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
