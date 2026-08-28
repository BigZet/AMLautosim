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
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.db.models.scoring_results import ScoringResult
from src.aml_workshop_simulator.db.session import get_db
from src.aml_workshop_simulator.domain.channels import channel_label
from src.aml_workshop_simulator.domain.rules import (
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
)
from src.aml_workshop_simulator.schemas.scenarios import (
    ScenarioOut,
    ScenarioPutIn,
    ScenarioSubmitIn,
)
from src.aml_workshop_simulator.services.leaderboard_service import (
    build_public_leaderboard,
)
from src.aml_workshop_simulator.services.scenario_service import (
    build_snapshot,
    canonical_steps,
    load_round_card_specs,
    payload_hash,
)

router = APIRouter()


def scenario_out(scenario: Scenario) -> ScenarioOut:
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
    )


async def _get_round(db: AsyncSession, round_id: int) -> Round:
    round_obj = (
        await db.execute(select(Round).where(Round.id == round_id))
    ).scalars().first()
    if round_obj is None:
        raise NotFound("Раунд не найден.", code="round_not_found")
    return round_obj


def card_out(row: ActionCard) -> ActionCardOut:
    spec = card_spec_from_row(row)
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
    return RoundPublicOut(
        id=round_obj.id,
        title=round_obj.title,
        status=round_obj.status,
        config_version=(round_obj.game_config or {}).get("config_version"),
        activated_at=round_obj.activated_at,
        game_config=round_obj.game_config or {},
    )


@router.get("/mine", response_model=RoundSummaryPageOut, operation_id="rounds_mine")
async def get_my_rounds(
    limit: int = Query(default=20, ge=1, le=100),
    principal: CurrentPrincipal = Depends(get_current_participant),
    db: AsyncSession = Depends(get_db),
) -> RoundSummaryPageOut:
    active_round = (
        await db.execute(select(Round).where(Round.status == "active"))
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
    rows = (await db.execute(select(ActionCard).order_by(ActionCard.id))).scalars().all()
    response.headers["ETag"] = str(
        (round_obj.game_config or {}).get("config_version", f"round-{round_obj.id}")
    )
    return [card_out(row) for row in rows if (row.code, row.version) in specs]


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
    scenario = (
        await db.execute(
            select(Scenario).where(
                Scenario.round_id == round_id,
                Scenario.participant_id == principal.user_id,
            )
        )
    ).scalars().first()
    return scenario_out(scenario) if scenario else None


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
    if round_obj.status != "active":
        raise Conflict(
            "Раунд закрыт для изменений: сценарий больше нельзя редактировать.",
            code="round_locked",
            details={"round_status": round_obj.status},
        )

    scenario = (
        await db.execute(
            select(Scenario)
            .where(
                Scenario.round_id == round_id,
                Scenario.participant_id == principal.user_id,
            )
            .with_for_update()
        )
    ).scalars().first()

    steps = canonical_steps(payload.steps)
    digest = payload_hash(steps)
    mutation_id = str(payload.client_mutation_id)

    # A retried request with the same mutation id must be answered before the
    # revision check: the client never saw the first response.
    if scenario is not None and str(scenario.last_client_mutation_id or "") == mutation_id:
        if scenario.payload_hash == digest:
            return scenario_out(scenario)
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

    specs = await load_round_card_specs(db, round_obj)
    try:
        snapshot = build_snapshot(steps, specs, round_obj.game_config)
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
            await db.commit()
        except IntegrityError as exc:  # concurrent first PUT from two windows
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
        await db.commit()

    await db.refresh(scenario)
    return scenario_out(scenario)


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
    if round_obj.status != "active":
        raise Conflict(
            "Раунд закрыт: отправка сценария больше недоступна.",
            code="round_locked",
            details={"round_status": round_obj.status},
        )

    scenario = (
        await db.execute(
            select(Scenario)
            .where(
                Scenario.round_id == round_id,
                Scenario.participant_id == principal.user_id,
            )
            .with_for_update()
        )
    ).scalars().first()
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
        return scenario_out(scenario)

    specs = await load_round_card_specs(db, round_obj)
    try:
        snapshot = build_snapshot(scenario.steps or [], specs, round_obj.game_config)
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
    await db.commit()
    await db.refresh(scenario)
    return scenario_out(scenario)


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

    scenario = (
        await db.execute(
            select(Scenario).where(
                Scenario.round_id == round_id,
                Scenario.participant_id == principal.user_id,
            )
        )
    ).scalars().first()
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
    principal: CurrentPrincipal | None = Depends(get_principal_optional),
    db: AsyncSession = Depends(get_db),
) -> LeaderboardPageOut:
    round_obj = await _get_round(db, round_id)
    generated_at = datetime.now(UTC)
    if round_obj.status != "completed":
        return LeaderboardPageOut(rows=[], next_cursor=None, generated_at=generated_at)

    board = await build_public_leaderboard(
        db, round_id, current_user_id=principal.user_id if principal else None
    )
    rows = [
        LeaderboardRowOut(
            rank=row["rank"],
            display_name=row["display_name"],
            game_score=row["game_score"],
            stealth_score=row["stealth_score"],
            resource_score=row["resource_score"],
            risk_label=row["risk_label"],
            is_adjusted=row["is_adjusted"],
            is_current_user=row["is_current_user"],
        )
        for row in board[:limit]
    ]
    return LeaderboardPageOut(rows=rows, next_cursor=None, generated_at=generated_at)
