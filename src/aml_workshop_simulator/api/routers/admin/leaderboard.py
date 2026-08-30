"""Manual leaderboard overlays and the administrator board.

The stored scoring result is immutable. An overlay only changes the *effective*
values, keeps its own revision for optimistic concurrency, and is always
recorded in the audit trail together with the value it replaced.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aml_workshop_simulator.api.deps import CurrentPrincipal, get_current_admin
from aml_workshop_simulator.api.errors import Conflict, NotFound, ValidationFailed
from aml_workshop_simulator.api.pagination import decode_cursor, encode_cursor
from aml_workshop_simulator.api.routers.admin.common import audit as _audit
from aml_workshop_simulator.api.routers.admin.common import get_round as _get_round
from aml_workshop_simulator.db.models.leaderboard_adjustments import (
    LeaderboardAdjustment,
)
from aml_workshop_simulator.db.models.scenarios import Scenario
from aml_workshop_simulator.db.models.scoring_results import ScoringResult
from aml_workshop_simulator.db.session import get_db
from aml_workshop_simulator.schemas.admin import (
    LeaderboardAdjustmentIn,
    LeaderboardAdjustmentOut,
)
from aml_workshop_simulator.schemas.leaderboard import (
    AdminLeaderboardPageOut,
    AdminLeaderboardRowOut,
)
from aml_workshop_simulator.services.leaderboard_service import (
    build_admin_leaderboard,
)

router = APIRouter()


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
    try:
        await db.commit()
    except IntegrityError as exc:
        # Two administrators created the first overlay at the same time: the
        # unique index decides, the loser retries with the new revision.
        await db.rollback()
        raise Conflict(
            "Корректировка уже создана другим администратором. Обновите страницу.",
            code="adjustment_revision_conflict",
            details={"current_revision": 1},
        ) from exc
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
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None),
    _: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminLeaderboardPageOut:
    await _get_round(db, round_id)
    board = await build_admin_leaderboard(db, round_id)
    # A ranking is only meaningful as a whole, so it is built whole and the
    # cursor is a position in it, as on the public board.
    after = decode_cursor(cursor, 1)
    start = int(after[0]) if after is not None else 0
    rows = board[start : start + limit]
    next_cursor = (
        encode_cursor([start + limit]) if len(board) > start + limit else None
    )
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
        next_cursor=next_cursor,
        generated_at=datetime.now(UTC),
    )
