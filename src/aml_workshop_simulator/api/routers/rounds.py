from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.api.deps import (
    CurrentPrincipal,
    get_current_participant,
    get_principal_optional,
)
from src.aml_workshop_simulator.api.errors import (
    Conflict,
    NotFound,
    ScenarioValidationFailed,
    ValidationFailed,
    first_message,
    violations_payload,
)
from src.aml_workshop_simulator.db.models.action_cards import ActionCard
from src.aml_workshop_simulator.db.models.leaderboard_adjustments import (
    LeaderboardAdjustment,
)
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.db.models.scenario_versions import ScenarioVersion
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.db.models.scoring_results import ScoringResult
from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.domain.channels import channel_label
from src.aml_workshop_simulator.domain.round_policy import (
    PARAM_CHANNEL,
    OperationPolicy,
    RoundPolicy,
    split_param,
)
from src.aml_workshop_simulator.domain.rules import (
    CardSpec,
    StructuralError,
    card_spec_from_row,
    submit_blockers,
)
from src.aml_workshop_simulator.schemas.leaderboard import (
    BaseResultOut,
    LeaderboardMetaOut,
    LeaderboardPageOut,
    LeaderboardRowOut,
    ResultOut,
)
from src.aml_workshop_simulator.schemas.rounds import (
    ActionCardOut,
    RoundPublicOut,
    RoundSummaryOut,
    RoundSummaryPageOut,
    VisibleParamOut,
)
from src.aml_workshop_simulator.schemas.scenarios import (
    ScenarioOut,
    ScenarioPreviewIn,
    ScenarioPreviewOut,
    ScenarioPutIn,
    ScenarioRestoreIn,
    ScenarioSubmitIn,
    ScenarioVersionOut,
    ScenarioVersionPageOut,
    ScenarioVersionSummaryOut,
)
from src.aml_workshop_simulator.services.audit import record_event
from src.aml_workshop_simulator.services.leaderboard_service import (
    build_public_leaderboard,
)
from src.aml_workshop_simulator.services.scenario_service import (
    build_snapshot,
    canonical_steps,
    load_round_card_specs,
    payload_hash,
    round_policy,
)
from src.aml_workshop_simulator.services.scenario_versions import (
    append_version,
    count_versions,
    get_version,
    list_versions,
    version_summary,
)

router = APIRouter()

#: Round states in which a participant may still change their chain.
EDITABLE_ROUND_STATUSES = {"active"}


async def scenario_out(db: AsyncSession, scenario: Scenario) -> ScenarioOut:
    submitted_revision: int | None = None
    if scenario.submitted_version_id is not None:
        submitted_revision = (
            await db.execute(
                select(ScenarioVersion.revision).where(
                    ScenarioVersion.id == scenario.submitted_version_id
                )
            )
        ).scalar()
    return ScenarioOut(
        id=scenario.id,
        round_id=scenario.round_id,
        participant_id=scenario.participant_id,
        status=scenario.status,
        revision=scenario.revision,
        steps=scenario.steps or [],
        resources=scenario.resource_snapshot or {},
        updated_at=scenario.updated_at,
        submitted_at=scenario.submitted_at,
        current_version_id=scenario.current_version_id,
        submitted_revision=submitted_revision,
        version_count=await count_versions(db, scenario.id),
    )


async def _get_round(db: AsyncSession, round_id: int) -> Round:
    round_obj = (
        await db.execute(select(Round).where(Round.id == round_id))
    ).scalars().first()
    if round_obj is None:
        raise NotFound("Раунд не найден.", code="round_not_found")
    return round_obj


def _require_editable(round_obj: Round, action: str) -> None:
    if round_obj.status in EDITABLE_ROUND_STATUSES:
        return
    messages = {
        "draft": "Раунд еще не запущен организатором: сценарий пока нельзя менять.",
        "stopped": "Раунд остановлен организатором: изменения больше не принимаются.",
        "scoring": "Идет подсчет результатов: изменения больше не принимаются.",
        "completed": "Раунд завершен: изменения больше не принимаются.",
    }
    raise Conflict(
        messages.get(round_obj.status, f"Раунд закрыт для действия «{action}»."),
        code="round_locked",
        details={"round_status": round_obj.status},
    )


def visible_param_out(spec: CardSpec, param: str) -> VisibleParamOut | None:
    field = spec.field_spec(param)
    if field is None:
        return None
    namespace, key = split_param(param)
    return VisibleParamOut(
        param=param,
        key=key,
        namespace=namespace,
        label=str(field.get("label", key)),
        kind=str(field.get("kind", "select")),
        help=field.get("help"),
        default=field.get("default"),
        options=[dict(option) for option in field.get("options", [])],
    )


def card_out(row: ActionCard, operation: OperationPolicy | None = None) -> ActionCardOut:
    spec = card_spec_from_row(row)
    if operation is not None:
        spec = spec.with_overrides(operation.overrides)
        params = operation.visible_params
        show_frequency = operation.show_frequency
        pinned = dict(operation.pinned)
    else:
        params = (PARAM_CHANNEL,) + tuple(
            item
            for item in spec.default_visible_params
            if item != PARAM_CHANNEL
        )
        show_frequency = spec.default_show_frequency
        pinned = {}
    visible = [
        rendered
        for rendered in (visible_param_out(spec, param) for param in params)
        if rendered is not None
    ]
    return ActionCardOut(
        id=spec.id,
        code=spec.code,
        version=spec.version,
        title=spec.title,
        description=spec.description,
        category=spec.category,
        flow=spec.flow,
        risk_weight=str(spec.risk_weight),
        costs={
            "energy": spec.energy_cost,
            "time": spec.time_cost,
            "trust": spec.trust_cost,
        },
        fee_rate=str(spec.fee_rate),
        min_amount=str(spec.min_amount),
        max_amount=str(spec.max_amount),
        max_frequency=spec.max_frequency,
        round_frequency_limit=spec.round_frequency_limit,
        requires_card_code=spec.requires_card_code,
        quota_category=spec.quota_category,
        channels=list(spec.channels),
        channel_labels={item: channel_label(item) for item in spec.channels},
        fields=[dict(item) for item in spec.fields],
        context_fields=[dict(item) for item in spec.context_fields],
        visible_params=visible,
        show_frequency=show_frequency,
        pinned_defaults=pinned,
    )


def round_public_out(round_obj: Round) -> RoundPublicOut:
    return RoundPublicOut(
        id=round_obj.id,
        title=round_obj.title,
        status=round_obj.status,
        config_version=(round_obj.game_config or {}).get("config_version"),
        activated_at=round_obj.activated_at,
        stopped_at=round_obj.stopped_at,
        completed_at=round_obj.completed_at,
        game_config=round_obj.game_config or {},
    )


@router.get("/active", response_model=RoundPublicOut | None, operation_id="rounds_active")
async def get_active_round(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> RoundPublicOut | None:
    round_obj = (
        await db.execute(select(Round).where(Round.status == "active"))
    ).scalars().first()
    if round_obj is None:
        return None
    response.headers["Cache-Control"] = "private, max-age=0"
    return round_public_out(round_obj)


@router.get(
    "/current", response_model=RoundPublicOut | None, operation_id="rounds_current"
)
async def get_current_round(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> RoundPublicOut | None:
    """The round the participant screen should show, whatever its state.

    Before the organiser presses «Начать раунд» there is no *active* round, but
    the participant still has to be told that a round exists and that they are
    waiting for it. The order is: the running round first, then the most recent
    finished one, then the newest draft.
    """
    response.headers["Cache-Control"] = "private, max-age=0"
    for statuses in (
        ("active", "scoring"),
        ("stopped",),
        ("completed",),
        ("draft",),
    ):
        round_obj = (
            await db.execute(
                select(Round)
                .where(Round.status.in_(statuses))
                .order_by(Round.id.desc())
                .limit(1)
            )
        ).scalars().first()
        if round_obj is not None:
            return round_public_out(round_obj)
    return None


@router.get("/mine", response_model=RoundSummaryPageOut, operation_id="rounds_mine")
async def get_my_rounds(
    limit: int = Query(default=20, ge=1, le=100),
    principal: CurrentPrincipal = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
) -> RoundSummaryPageOut:
    active_round = (
        await db.execute(
            select(Round)
            .where(Round.status.in_(["active", "stopped", "scoring"]))
            .order_by(Round.id.desc())
            .limit(1)
        )
    ).scalars().first()

    rows = (
        await db.execute(
            select(Scenario, Round)
            .join(Round, Scenario.round_id == Round.id)
            .where(Scenario.participant_id == principal.user_id)
            .order_by(desc(Round.id))
            .limit(limit)
        )
    ).all()

    result_ids = {
        scenario_id
        for (scenario_id,) in (
            await db.execute(
                select(ScoringResult.scenario_id).where(
                    ScoringResult.scenario_id.in_([s.id for s, _ in rows] or [0])
                )
            )
        ).all()
    }

    summaries: list[RoundSummaryOut] = []
    seen: set[int] = set()

    if active_round is not None:
        seen.add(active_round.id)
        own = next((s for s, r in rows if r.id == active_round.id), None)
        summaries.append(
            RoundSummaryOut(
                id=active_round.id,
                title=active_round.title,
                status=active_round.status,
                scenario_status=own.status if own else None,
                result_available=False,
                completed_at=None,
            )
        )

    for scenario, round_obj in rows:
        if round_obj.id in seen:
            continue
        seen.add(round_obj.id)
        summaries.append(
            RoundSummaryOut(
                id=round_obj.id,
                title=round_obj.title,
                status=round_obj.status,
                scenario_status=scenario.status,
                result_available=scenario.id in result_ids,
                completed_at=round_obj.completed_at,
            )
        )
    return RoundSummaryPageOut(rows=summaries, next_cursor=None)


@router.get(
    "/{round_id}/cards",
    response_model=list[ActionCardOut],
    operation_id="rounds_cards",
)
async def get_round_cards(
    round_id: int,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> list[ActionCardOut]:
    round_obj = await _get_round(db, round_id)
    specs = await load_round_card_specs(db, round_obj)
    policy = round_policy(round_obj, specs)
    rows = (await db.execute(select(ActionCard).order_by(ActionCard.id))).scalars().all()
    response.headers["ETag"] = str(
        (round_obj.game_config or {}).get("config_version", f"round-{round_obj.id}")
    )
    return [
        card_out(row, policy.for_card((row.code, row.version)))
        for row in rows
        if (row.code, row.version) in specs
    ]


async def _load_scenario(
    db: AsyncSession, round_id: int, participant_id: int, lock: bool = False
) -> Scenario | None:
    stmt = select(Scenario).where(
        Scenario.round_id == round_id, Scenario.participant_id == participant_id
    )
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalars().first()


@router.get(
    "/{round_id}/scenario",
    response_model=ScenarioOut | None,
    operation_id="rounds_scenario_get",
)
async def get_my_scenario(
    round_id: int,
    principal: CurrentPrincipal = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
) -> ScenarioOut | None:
    await _get_round(db, round_id)
    scenario = await _load_scenario(db, round_id, principal.user_id)
    return await scenario_out(db, scenario) if scenario else None


@router.post(
    "/{round_id}/scenario/preview",
    response_model=ScenarioPreviewOut,
    operation_id="rounds_scenario_preview",
)
async def preview_scenario(
    round_id: int,
    payload: ScenarioPreviewIn,
    _: CurrentPrincipal = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
) -> ScenarioPreviewOut:
    """Evaluate a candidate chain without touching the database.

    The participant UI calls this after every change to the chain, so the
    numbers on screen are always the server's own numbers — there is no second
    implementation of the rules that could drift.
    """
    round_obj = await _get_round(db, round_id)
    specs = await load_round_card_specs(db, round_obj)
    policy = round_policy(round_obj, specs)
    steps = canonical_steps(payload.steps, specs, policy)
    try:
        snapshot = build_snapshot(steps, specs, round_obj.game_config, policy)
    except StructuralError as exc:
        violations = [item.as_dict() for item in exc.violations]
        raise ValidationFailed(
            first_message(violations, "Шаг не соответствует контракту карточки"),
            code="validation_error",
            details=violations_payload(violations),
        ) from exc
    return ScenarioPreviewOut(resources=snapshot, blockers=submit_blockers(snapshot))


@router.put(
    "/{round_id}/scenario",
    response_model=ScenarioOut,
    operation_id="rounds_scenario_put",
)
async def put_scenario(
    round_id: int,
    payload: ScenarioPutIn,
    principal: CurrentPrincipal = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
) -> ScenarioOut:
    round_obj = await _get_round(db, round_id)
    _require_editable(round_obj, "сохранение сценария")

    scenario = await _load_scenario(db, round_id, principal.user_id, lock=True)

    specs = await load_round_card_specs(db, round_obj)
    policy = round_policy(round_obj, specs)
    steps = canonical_steps(payload.steps, specs, policy)
    digest = payload_hash(steps)
    mutation_id = str(payload.client_mutation_id)

    # A retried request with the same mutation id must be answered before the
    # revision check: the client never saw the first response.
    if scenario is not None and str(scenario.last_client_mutation_id or "") == mutation_id:
        if scenario.payload_hash == digest:
            return await scenario_out(db, scenario)
        raise Conflict(
            "Идентификатор команды уже использован с другим содержимым. "
            "Повторите сохранение с новым идентификатором.",
            code="mutation_id_reused",
            details={"current_revision": scenario.revision},
        )

    current_revision = scenario.revision if scenario else 0
    if payload.expected_revision != current_revision:
        raise Conflict(
            "Сценарий изменен в другом окне. Обновите страницу, чтобы увидеть "
            f"актуальную версию (ревизия {current_revision}).",
            code="scenario_revision_conflict",
            details={
                "current_revision": current_revision,
                "current_updated_at": (
                    scenario.updated_at.isoformat() if scenario else None
                ),
            },
        )

    try:
        snapshot = build_snapshot(steps, specs, round_obj.game_config, policy)
    except StructuralError as exc:
        violations = [item.as_dict() for item in exc.violations]
        raise ValidationFailed(
            first_message(violations, "Шаг не соответствует контракту карточки"),
            code="validation_error",
            details=violations_payload(violations),
        ) from exc

    now = datetime.now(UTC)
    if scenario is None:
        scenario = Scenario(
            round_id=round_id,
            participant_id=principal.user_id,
            status="draft",
            steps=steps,
            resource_snapshot=snapshot,
            revision=1,
            last_client_mutation_id=payload.client_mutation_id,
            payload_hash=digest,
            updated_at=now,
        )
        db.add(scenario)
        try:
            await db.flush()
        except IntegrityError as exc:  # concurrent first PUT from two windows
            await db.rollback()
            raise Conflict(
                "Сценарий уже создан в другом окне. Обновите страницу.",
                code="scenario_revision_conflict",
                details={"current_revision": 1},
            ) from exc
        await append_version(
            db,
            scenario,
            steps=steps,
            snapshot=snapshot,
            payload_hash=digest,
            created_by_user_id=principal.user_id,
            label=payload.label,
        )
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise Conflict(
                "Сценарий уже создан в другом окне. Обновите страницу.",
                code="scenario_revision_conflict",
                details={"current_revision": 1},
            ) from exc
    else:
        identical = scenario.payload_hash == digest
        scenario.steps = steps
        scenario.resource_snapshot = snapshot
        scenario.payload_hash = digest
        scenario.last_client_mutation_id = payload.client_mutation_id
        scenario.updated_at = now
        if not identical:
            scenario.revision += 1
            if scenario.status != "draft":
                # Editing a submitted scenario in an active round reopens it.
                scenario.status = "draft"
                scenario.submitted_at = None
                scenario.submitted_version_id = None
            await append_version(
                db,
                scenario,
                steps=steps,
                snapshot=snapshot,
                payload_hash=digest,
                created_by_user_id=principal.user_id,
                label=payload.label,
            )
        await db.commit()

    await db.refresh(scenario)
    return await scenario_out(db, scenario)


@router.get(
    "/{round_id}/scenario/versions",
    response_model=ScenarioVersionPageOut,
    operation_id="rounds_scenario_versions",
)
async def list_scenario_versions(
    round_id: int,
    principal: CurrentPrincipal = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
) -> ScenarioVersionPageOut:
    await _get_round(db, round_id)
    scenario = await _load_scenario(db, round_id, principal.user_id)
    if scenario is None:
        return ScenarioVersionPageOut(rows=[])
    rows = [
        ScenarioVersionSummaryOut(
            **version_summary(
                version,
                is_current=version.id == scenario.current_version_id,
                is_submitted=version.id == scenario.submitted_version_id,
            )
        )
        for version in await list_versions(db, scenario.id)
    ]
    return ScenarioVersionPageOut(rows=rows)


@router.get(
    "/{round_id}/scenario/versions/{revision}",
    response_model=ScenarioVersionOut,
    operation_id="rounds_scenario_version_get",
)
async def get_scenario_version(
    round_id: int,
    revision: int,
    principal: CurrentPrincipal = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
) -> ScenarioVersionOut:
    await _get_round(db, round_id)
    scenario = await _load_scenario(db, round_id, principal.user_id)
    if scenario is None:
        raise NotFound("Сценарий не найден.", code="scenario_not_found")
    version = await get_version(db, scenario.id, revision)
    if version is None:
        raise NotFound("Версия черновика не найдена.", code="scenario_version_not_found")
    return ScenarioVersionOut(
        **version_summary(
            version,
            is_current=version.id == scenario.current_version_id,
            is_submitted=version.id == scenario.submitted_version_id,
        ),
        steps=version.steps or [],
        resources=version.resource_snapshot or {},
    )


@router.post(
    "/{round_id}/scenario/versions/{revision}/restore",
    response_model=ScenarioOut,
    operation_id="rounds_scenario_version_restore",
)
async def restore_scenario_version(
    round_id: int,
    revision: int,
    payload: ScenarioRestoreIn,
    principal: CurrentPrincipal = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
) -> ScenarioOut:
    """Continue from an older version by appending a copy of it.

    Nothing saved after `revision` is deleted: the history keeps growing and the
    restored chain simply becomes the newest version.
    """
    round_obj = await _get_round(db, round_id)
    _require_editable(round_obj, "восстановление версии")

    scenario = await _load_scenario(db, round_id, principal.user_id, lock=True)
    if scenario is None:
        raise NotFound("Сценарий не найден.", code="scenario_not_found")

    mutation_id = str(payload.client_mutation_id)
    if str(scenario.last_client_mutation_id or "") == mutation_id:
        return await scenario_out(db, scenario)

    if scenario.revision != payload.expected_revision:
        raise Conflict(
            "Сценарий изменен в другом окне. Обновите страницу, чтобы увидеть "
            f"актуальную версию (ревизия {scenario.revision}).",
            code="scenario_revision_conflict",
            details={"current_revision": scenario.revision},
        )

    version = await get_version(db, scenario.id, revision)
    if version is None:
        raise NotFound("Версия черновика не найдена.", code="scenario_version_not_found")

    specs = await load_round_card_specs(db, round_obj)
    policy = round_policy(round_obj, specs)
    steps = [dict(step) for step in (version.steps or [])]
    try:
        snapshot = build_snapshot(steps, specs, round_obj.game_config, policy)
    except StructuralError as exc:
        violations = [item.as_dict() for item in exc.violations]
        raise ValidationFailed(
            first_message(
                violations,
                "Сохраненная версия больше не соответствует контракту карточек",
            ),
            code="validation_error",
            details=violations_payload(violations),
        ) from exc

    now = datetime.now(UTC)
    scenario.steps = steps
    scenario.resource_snapshot = snapshot
    scenario.payload_hash = payload_hash(steps)
    scenario.last_client_mutation_id = payload.client_mutation_id
    scenario.updated_at = now
    scenario.revision += 1
    scenario.status = "draft"
    scenario.submitted_at = None
    scenario.submitted_version_id = None
    await append_version(
        db,
        scenario,
        steps=steps,
        snapshot=snapshot,
        payload_hash=scenario.payload_hash,
        created_by_user_id=principal.user_id,
        label=payload.label or f"Возврат к версии {revision}",
        restored_from_revision=revision,
    )
    await record_event(
        db,
        actor_user_id=principal.user_id,
        event_type="scenario_version_restored",
        round_id=round_id,
        scenario_id=scenario.id,
        target_type="scenario_version",
        target_id=str(revision),
        metadata={"restored_from_revision": revision, "revision": scenario.revision},
    )
    await db.commit()
    await db.refresh(scenario)
    return await scenario_out(db, scenario)


@router.post(
    "/{round_id}/scenario/submit",
    response_model=ScenarioOut,
    operation_id="rounds_scenario_submit",
)
async def submit_scenario(
    round_id: int,
    payload: ScenarioSubmitIn,
    principal: CurrentPrincipal = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
) -> ScenarioOut:
    round_obj = await _get_round(db, round_id)
    _require_editable(round_obj, "отправка сценария")

    scenario = await _load_scenario(db, round_id, principal.user_id, lock=True)
    if scenario is None:
        raise NotFound(
            "Сценарий не найден. Сначала сохраните черновик.", code="scenario_not_found"
        )

    if scenario.revision != payload.expected_revision:
        raise Conflict(
            "Отправляемая ревизия устарела. Сохраните черновик заново и повторите "
            f"отправку (актуальная ревизия {scenario.revision}).",
            code="scenario_revision_conflict",
            details={"current_revision": scenario.revision},
        )

    if scenario.status in {"submitted", "scored"}:
        # Idempotent repeat of the same revision.
        return await scenario_out(db, scenario)

    specs = await load_round_card_specs(db, round_obj)
    policy = round_policy(round_obj, specs)
    try:
        snapshot = build_snapshot(scenario.steps or [], specs, round_obj.game_config, policy)
    except StructuralError as exc:
        violations = [item.as_dict() for item in exc.violations]
        raise ValidationFailed(
            first_message(violations, "Сценарий не соответствует контракту карточек"),
            details=violations_payload(violations),
        ) from exc

    blockers = submit_blockers(snapshot)
    scenario.resource_snapshot = snapshot
    if blockers:
        await db.commit()
        raise ScenarioValidationFailed(
            first_message(blockers, "Сценарий нарушает правила раунда"),
            details=violations_payload(blockers),
        )

    now = datetime.now(UTC)
    scenario.status = "submitted"
    scenario.submitted_at = now
    scenario.updated_at = now
    # Submitting freezes one concrete version; scoring reads only that row.
    scenario.submitted_version_id = scenario.current_version_id
    if scenario.current_version_id is not None:
        current = (
            await db.execute(
                select(ScenarioVersion).where(
                    ScenarioVersion.id == scenario.current_version_id
                )
            )
        ).scalars().first()
        if current is not None:
            current.resource_snapshot = snapshot
    await record_event(
        db,
        actor_user_id=principal.user_id,
        event_type="scenario_submitted",
        round_id=round_id,
        scenario_id=scenario.id,
        target_type="scenario",
        target_id=str(scenario.id),
        metadata={
            "revision": scenario.revision,
            "step_count": len(scenario.steps or []),
        },
    )
    await db.commit()
    await db.refresh(scenario)
    return await scenario_out(db, scenario)


@router.get(
    "/{round_id}/result",
    response_model=ResultOut | None,
    operation_id="rounds_result",
)
async def get_my_result(
    round_id: int,
    principal: CurrentPrincipal = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
) -> ResultOut | None:
    round_obj = await _get_round(db, round_id)
    if round_obj.status != "completed":
        return None

    scenario = await _load_scenario(db, round_id, principal.user_id)
    if scenario is None:
        return None

    result = (
        await db.execute(
            select(ScoringResult).where(ScoringResult.scenario_id == scenario.id)
        )
    ).scalars().first()
    if result is None:
        return None

    adjustment = (
        await db.execute(
            select(LeaderboardAdjustment).where(
                LeaderboardAdjustment.scenario_id == scenario.id
            )
        )
    ).scalars().first()

    board = await build_public_leaderboard(db, round_id, current_user_id=principal.user_id)
    rank = next(
        (row["rank"] for row in board if row["scenario_id"] == scenario.id),
        len(board) + 1,
    )
    effective = (
        adjustment.game_score_override
        if adjustment and adjustment.game_score_override is not None
        else result.game_score
    )
    return ResultOut(
        scenario_id=scenario.id,
        base=BaseResultOut(
            risk_score=str(result.risk_score),
            risk_label=result.risk_label,
            stealth_score=str(result.stealth_score),
            resource_score=str(result.resource_score),
            game_score=str(result.game_score),
        ),
        leaderboard=LeaderboardMetaOut(
            effective_game_score=str(Decimal(str(effective))),
            rank=rank,
            is_adjusted=adjustment is not None,
        ),
        versions={
            "scoring": result.scoring_version,
            "leaderboard": result.leaderboard_version,
        },
        explanation=result.explanation or {},
        resources=scenario.resource_snapshot or {},
    )


@router.get(
    "/{round_id}/leaderboard",
    response_model=LeaderboardPageOut,
    operation_id="rounds_leaderboard",
)
async def get_public_leaderboard(
    round_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    reveal: bool = Query(
        default=False,
        description=(
            "Explicitly ask for the real nicknames. The default projection "
            "carries masked placeholders only."
        ),
    ),
    principal: CurrentPrincipal | None = Depends(get_principal_optional),
    db: AsyncSession = Depends(get_db),
) -> LeaderboardPageOut:
    """Public board.

    Nicknames are hidden by default: the response literally contains
    `Игрок #1`, `Игрок #2`, … and no participant name at all, so a nickname
    cannot leak through the page source before the organiser or the player asks
    for it. Passing `reveal=true` is the explicit request that returns the real
    display names.
    """
    round_obj = await _get_round(db, round_id)
    generated_at = datetime.now(UTC)
    if round_obj.status != "completed":
        return LeaderboardPageOut(
            rows=[], next_cursor=None, generated_at=generated_at, revealed=reveal
        )

    board = await build_public_leaderboard(
        db, round_id, current_user_id=principal.user_id if principal else None
    )
    rows = [
        LeaderboardRowOut(
            rank=row["rank"],
            display_name=(
                row["display_name"] if reveal else f"Игрок #{position}"
            ),
            masked=not reveal,
            game_score=row["game_score"],
            stealth_score=row["stealth_score"],
            resource_score=row["resource_score"],
            risk_label=row["risk_label"],
            is_adjusted=row["is_adjusted"],
            is_current_user=row["is_current_user"],
        )
        for position, row in enumerate(board[:limit], start=1)
    ]
    return LeaderboardPageOut(
        rows=rows, next_cursor=None, generated_at=generated_at, revealed=reveal
    )
