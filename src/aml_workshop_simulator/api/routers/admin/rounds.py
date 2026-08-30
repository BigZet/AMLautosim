"""Round catalogue, configuration and lifecycle.

The lifecycle is an explicit state machine:

``draft`` → ``active`` → ``stopped`` → ``scoring`` → ``completed``

* the organiser must **start** a round before anybody can play it;
* **stop** freezes it — every write from a participant is refused, nothing is
  deleted, and the round can still be scored;
* **restart** never destroys anything: it creates a *new* round carrying the
  same configuration and a link back to the round it replaces.

PostgreSQL guarantees the single-active invariant through the partial unique
index `uq_rounds_single_active`; the endpoints additionally take a row lock so
two administrators clicking at the same time serialise instead of racing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aml_workshop_simulator.api.deps import CurrentPrincipal, get_current_admin
from aml_workshop_simulator.api.errors import ApiError, Conflict, NotFound
from aml_workshop_simulator.api.routers.admin.common import (
    ROUND_STATUS_LABELS,
    audit,
    config_version,
    get_round,
    require_confirmation,
    round_out,
    validate_game_config,
)
from aml_workshop_simulator.api.routers.rounds import card_out
from aml_workshop_simulator.core.logging import log_event
from aml_workshop_simulator.core.security import hash_idempotency_key
from aml_workshop_simulator.db.models.action_cards import ActionCard
from aml_workshop_simulator.db.models.round_presets import RoundPreset
from aml_workshop_simulator.db.models.rounds import Round
from aml_workshop_simulator.db.models.scenario_versions import ScenarioVersion
from aml_workshop_simulator.db.models.scenarios import Scenario
from aml_workshop_simulator.db.models.scoring_results import ScoringResult
from aml_workshop_simulator.db.models.users import User
from aml_workshop_simulator.db.session import get_db
from aml_workshop_simulator.domain.scoring import (
    LEADERBOARD_VERSION,
    SCORING_VERSION,
)
from aml_workshop_simulator.schemas.admin import (
    RoundAdminOut,
    RoundCreateIn,
    RoundLifecycleIn,
    RoundRestartIn,
    RoundStatsOut,
    RoundUpdateIn,
    ScoringPlanOut,
    ScoringSummaryOut,
)
from aml_workshop_simulator.schemas.rounds import ActionCardOut
from aml_workshop_simulator.services.configuration import freeze_game_config
from aml_workshop_simulator.services.scoring_service import (
    NoSubmissions,
    score_round,
)

router = APIRouter()


# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------


@router.get("/game-config/default", operation_id="admin_default_game_config")
async def default_game_config(
    _: CurrentPrincipal = Depends(get_current_admin),
) -> dict[str, Any]:
    from aml_workshop_simulator.core.game_config import base_game_config
    from aml_workshop_simulator.schemas.round_config import GameConfigIn
    return GameConfigIn.model_validate(base_game_config()).dump()


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
    """Create a draft round from an explicit configuration or from a preset.

    The preset is only a template: its configuration is copied into the round's
    own snapshot, so later edits to the preset never reach an existing round.
    """
    preset: RoundPreset | None = None
    if payload.preset_id is not None:
        preset = (
            await db.execute(
                select(RoundPreset).where(RoundPreset.id == payload.preset_id)
            )
        ).scalars().first()
        if preset is None:
            raise NotFound("Пресет не найден.", code="preset_not_found")

    if payload.game_config is not None:
        game_config = payload.game_config.dump()
    elif preset is not None:
        game_config = dict(preset.game_config)
    else:
        raise Conflict(
            "Укажите конфигурацию раунда или выберите пресет.",
            code="round_configuration_invalid",
        )

    cards = (await db.execute(select(ActionCard))).scalars().all()
    validate_game_config(list(cards), game_config)
    game_config = freeze_game_config(game_config, list(cards))

    now = datetime.now(UTC)
    round_obj = Round(
        title=payload.title,
        status="draft",
        config_revision=1,
        game_config=game_config,
        created_by_user_id=principal.user_id,
        created_at=now,
        preset_id=preset.id if preset else None,
    )
    db.add(round_obj)
    await db.flush()
    await audit(
        db,
        actor_user_id=principal.user_id,
        event_type="round_created",
        round_id=round_obj.id,
        target_type="round",
        target_id=str(round_obj.id),
        request_id=getattr(request.state, "request_id", None),
        metadata={"preset_id": preset.id if preset else None},
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
async def get_round_detail(
    round_id: int,
    _: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> RoundAdminOut:
    return round_out(await get_round(db, round_id))


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
    round_obj = await get_round(db, round_id)
    if round_obj.status != "draft":
        raise Conflict(
            "Конфигурация запущенного раунда неизменяема. Создайте новый черновик "
            "или перезапустите раунд с новой конфигурацией.",
            code="round_config_locked",
            details={"round_status": round_obj.status},
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
        game_config = payload.game_config.dump()
        cards = (await db.execute(select(ActionCard))).scalars().all()
        try:
            game_config = freeze_game_config(
                game_config, [card for card in cards if card.is_active], round_obj.game_config
            )
        except ValueError as error:
            raise Conflict(str(error), code="round_configuration_invalid") from error
        validate_game_config(list(cards), game_config)
        round_obj.game_config = game_config
    round_obj.config_revision += 1
    await audit(
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


async def _lock_round(db: AsyncSession, round_id: int) -> Round:
    """Serialise concurrent lifecycle commands on one round."""
    await get_round(db, round_id)
    locked = (
        await db.execute(select(Round).where(Round.id == round_id).with_for_update())
    ).scalars().first()
    if locked is None:  # pragma: no cover - deleted between the two reads
        raise NotFound("Раунд не найден.", code="round_not_found")
    return locked


async def _start(
    db: AsyncSession,
    round_obj: Round,
    principal: CurrentPrincipal,
    request: Request,
    idempotency_key: str | None,
) -> Round:
    if round_obj.status == "active":
        return round_obj
    if round_obj.status in {"scoring", "completed"}:
        raise Conflict(
            "Раунд уже завершен и не может быть запущен повторно. "
            "Используйте перезапуск, чтобы создать новый раунд.",
            code="round_locked",
            details={"round_status": round_obj.status},
        )

    other = (
        await db.execute(
            select(Round).where(
                Round.status.in_(["active", "scoring"]), Round.id != round_obj.id
            )
        )
    ).scalars().first()
    if other is not None:
        raise Conflict(
            f"Уже есть активный раунд #{other.id}. Остановите его перед запуском нового.",
            code="active_round_exists",
            details={"active_round_id": other.id},
        )

    cards = (await db.execute(select(ActionCard))).scalars().all()
    game_config = dict(round_obj.game_config or {})
    validate_game_config(list(cards), game_config)
    game_config = freeze_game_config(game_config, list(cards))
    game_config["config_version"] = config_version(game_config)

    now = datetime.now(UTC)
    round_obj.game_config = game_config
    round_obj.status = "active"
    round_obj.activated_at = now
    round_obj.stopped_at = None
    await audit(
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
        raise Conflict("Другой раунд уже активен.", code="active_round_exists") from exc
    await db.refresh(round_obj)
    return round_obj


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
    """«Начать раунд». Idempotent: a second click returns the running round."""
    round_obj = await _lock_round(db, round_id)
    return round_out(await _start(db, round_obj, principal, request, idempotency_key))


@router.post(
    "/rounds/{round_id}/start",
    response_model=RoundAdminOut,
    operation_id="admin_round_start",
)
async def start_round(
    round_id: int,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> RoundAdminOut:
    """Explicit alias of `activate` that matches the button in the admin UI."""
    round_obj = await _lock_round(db, round_id)
    return round_out(await _start(db, round_obj, principal, request, idempotency_key))


@router.post(
    "/rounds/{round_id}/stop",
    response_model=RoundAdminOut,
    operation_id="admin_round_stop",
)
async def stop_round(
    round_id: int,
    payload: RoundLifecycleIn,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> RoundAdminOut:
    """«Остановить раунд»: no further participant writes, nothing deleted."""
    require_confirmation(payload.confirm, "остановка раунда")
    round_obj = await _lock_round(db, round_id)
    if round_obj.status == "stopped":
        return round_out(round_obj)
    if round_obj.status != "active":
        raise Conflict(
            "Остановить можно только идущий раунд (текущий статус: "
            f"{ROUND_STATUS_LABELS.get(round_obj.status, round_obj.status)}).",
            code="round_locked",
            details={"round_status": round_obj.status},
        )

    now = datetime.now(UTC)
    round_obj.status = "stopped"
    round_obj.stopped_at = now
    await audit(
        db,
        actor_user_id=principal.user_id,
        event_type="round_stopped",
        round_id=round_obj.id,
        target_type="round",
        target_id=str(round_obj.id),
        reason=payload.reason,
        request_id=getattr(request.state, "request_id", None),
        idempotency_key_hash=(
            hash_idempotency_key(idempotency_key) if idempotency_key else None
        ),
    )
    await db.commit()
    await db.refresh(round_obj)
    return round_out(round_obj)


@router.post(
    "/rounds/{round_id}/restart",
    response_model=RoundAdminOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="admin_round_restart",
)
async def restart_round(
    round_id: int,
    payload: RoundRestartIn,
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> RoundAdminOut:
    """«Перезапустить раунд».

    Creates a new round with the same configuration and a link back to the
    previous one. Scenarios, drafts, results and the audit trail of the old
    round are kept exactly as they are; the old round is simply stopped.
    """
    require_confirmation(payload.confirm, "перезапуск раунда")
    source = await _lock_round(db, round_id)

    existing = (
        await db.execute(
            select(Round)
            .where(Round.restarted_from_round_id == source.id)
            .order_by(Round.id.desc())
        )
    ).scalars().first()
    if existing is not None:
        # A second click (or a retried request) must not create a second round.
        return round_out(existing)

    if source.status == "active":
        source.status = "stopped"
        source.stopped_at = datetime.now(UTC)
    elif source.status == "scoring":
        raise Conflict(
            "Дождитесь окончания подсчета результатов, затем перезапустите раунд.",
            code="round_locked",
            details={"round_status": source.status},
        )

    game_config = {
        key: value
        for key, value in dict(source.game_config or {}).items()
        if key != "config_version"
    }
    cards = (await db.execute(select(ActionCard))).scalars().all()
    validate_game_config(list(cards), game_config)
    game_config = freeze_game_config(game_config, list(cards))

    now = datetime.now(UTC)
    replacement = Round(
        title=payload.title or f"{source.title} (перезапуск)",
        status="draft",
        config_revision=1,
        game_config=game_config,
        created_by_user_id=principal.user_id,
        created_at=now,
        restarted_from_round_id=source.id,
        preset_id=source.preset_id,
    )
    db.add(replacement)
    await db.flush()
    await audit(
        db,
        actor_user_id=principal.user_id,
        event_type="round_restarted",
        round_id=replacement.id,
        target_type="round",
        target_id=str(replacement.id),
        reason=payload.reason,
        request_id=getattr(request.state, "request_id", None),
        idempotency_key_hash=(
            hash_idempotency_key(idempotency_key) if idempotency_key else None
        ),
        metadata={"restarted_from_round_id": source.id},
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict(
            "Раунд уже перезапущен другим администратором. Обновите список раундов.",
            code="round_already_restarted",
        ) from exc
    await db.refresh(replacement)

    if payload.activate:
        locked = await _lock_round(db, replacement.id)
        return round_out(await _start(db, locked, principal, request, idempotency_key))
    return round_out(replacement)


@router.get(
    "/rounds/{round_id}/scoring-plan",
    response_model=ScoringPlanOut,
    operation_id="admin_round_scoring_plan",
)
async def scoring_plan(
    round_id: int,
    _: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ScoringPlanOut:
    """What a scoring run would include, so the organiser can confirm it."""
    round_obj = await get_round(db, round_id)

    async def count(status_value: str) -> int:
        return int(
            (
                await db.execute(
                    select(func.count(Scenario.id)).where(
                        Scenario.round_id == round_id, Scenario.status == status_value
                    )
                )
            ).scalar()
            or 0
        )

    submitted = await count("submitted")
    drafts = await count("draft")
    scored = await count("scored")

    blocker: str | None = None
    if round_obj.status == "completed":
        blocker = "Раунд уже завершен: результаты рассчитаны."
    elif round_obj.status not in {"active", "stopped"}:
        blocker = (
            "Скоринг доступен для идущего или остановленного раунда (текущий статус: "
            f"{ROUND_STATUS_LABELS.get(round_obj.status, round_obj.status)})."
        )
    elif submitted == 0:
        blocker = "В раунде нет отправленных сценариев: считать нечего."

    return ScoringPlanOut(
        round_id=round_id,
        round_status=round_obj.status,
        submitted_count=submitted,
        excluded_draft_count=drafts,
        already_scored_count=scored,
        can_score=blocker is None,
        blocker=blocker,
    )


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
    round_obj = await get_round(db, round_id)

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

    if round_obj.status not in {"active", "stopped"}:
        raise Conflict(
            "Скоринг доступен для идущего или остановленного раунда.",
            code="round_locked",
            details={"round_status": round_obj.status},
        )

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
    log_event(
        "round_scored",
        round_id=locked.id,
        count=summary["scored_count"],
        duration_ms=summary["duration_ms"],
        round_status=locked.status,
    )
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
    await get_round(db, round_id)

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
    versions = await count(
        select(func.count(ScenarioVersion.id))
        .select_from(ScenarioVersion)
        .join(Scenario, Scenario.id == ScenarioVersion.scenario_id)
        .where(Scenario.round_id == round_id)
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
        saved_versions=versions,
        last_scenario_update_at=last_update,
    )
