"""Reusable round configurations.

A preset is prepared before the workshop and never starts anything by itself:
loading it fills the editor, creating a round copies it into that round's own
immutable snapshot, and starting the round stays a separate, explicit command.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aml_workshop_simulator.api.deps import CurrentPrincipal, get_current_admin
from aml_workshop_simulator.api.errors import Conflict, NotFound
from aml_workshop_simulator.api.routers.admin.common import audit, validate_game_config
from aml_workshop_simulator.db.models.action_cards import ActionCard
from aml_workshop_simulator.db.models.round_presets import RoundPreset
from aml_workshop_simulator.db.models.rounds import Round
from aml_workshop_simulator.db.session import get_db
from aml_workshop_simulator.schemas.round_config import (
    RoundPresetIn,
    RoundPresetOut,
    RoundPresetUpdateIn,
)

router = APIRouter()


def preset_out(preset: RoundPreset) -> RoundPresetOut:
    return RoundPresetOut(
        id=preset.id,
        name=preset.name,
        description=preset.description,
        revision=preset.revision,
        game_config=preset.game_config,
        created_by_user_id=preset.created_by_user_id,
        updated_by_user_id=preset.updated_by_user_id,
        created_at=preset.created_at,
        updated_at=preset.updated_at,
    )


async def _get_preset(db: AsyncSession, preset_id: int) -> RoundPreset:
    preset = (
        await db.execute(select(RoundPreset).where(RoundPreset.id == preset_id))
    ).scalars().first()
    if preset is None:
        raise NotFound("Пресет не найден.", code="preset_not_found")
    return preset


@router.get(
    "/round-presets",
    response_model=list[RoundPresetOut],
    operation_id="admin_preset_list",
)
async def list_presets(
    _: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> list[RoundPresetOut]:
    rows = (
        (await db.execute(select(RoundPreset).order_by(RoundPreset.name)))
        .scalars()
        .all()
    )
    return [preset_out(item) for item in rows]


@router.get(
    "/round-presets/{preset_id}",
    response_model=RoundPresetOut,
    operation_id="admin_preset_get",
)
async def get_preset(
    preset_id: int,
    _: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> RoundPresetOut:
    return preset_out(await _get_preset(db, preset_id))


@router.post(
    "/round-presets",
    response_model=RoundPresetOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="admin_preset_create",
)
async def create_preset(
    payload: RoundPresetIn,
    request: Request,
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> RoundPresetOut:
    game_config = payload.game_config.dump()
    cards = (await db.execute(select(ActionCard))).scalars().all()
    validate_game_config(list(cards), game_config)

    now = datetime.now(UTC)
    preset = RoundPreset(
        name=payload.name.strip(),
        description=payload.description,
        game_config=game_config,
        revision=1,
        created_by_user_id=principal.user_id,
        updated_by_user_id=principal.user_id,
        created_at=now,
        updated_at=now,
    )
    db.add(preset)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict(
            "Пресет с таким названием уже существует.", code="preset_name_taken"
        ) from exc
    await audit(
        db,
        actor_user_id=principal.user_id,
        event_type="round_preset_created",
        target_type="round_preset",
        target_id=str(preset.id),
        reason=preset.name,
        request_id=getattr(request.state, "request_id", None),
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict(
            "Пресет с таким названием уже существует.", code="preset_name_taken"
        ) from exc
    await db.refresh(preset)
    return preset_out(preset)


@router.put(
    "/round-presets/{preset_id}",
    response_model=RoundPresetOut,
    operation_id="admin_preset_update",
)
async def update_preset(
    preset_id: int,
    payload: RoundPresetUpdateIn,
    request: Request,
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> RoundPresetOut:
    preset = await _get_preset(db, preset_id)
    if preset.revision != payload.expected_revision:
        raise Conflict(
            "Пресет изменен другим администратором "
            f"(актуальная ревизия {preset.revision}).",
            code="preset_revision_conflict",
            details={"current_revision": preset.revision},
        )
    if payload.name is not None:
        preset.name = payload.name.strip()
    if payload.description is not None:
        preset.description = payload.description
    if payload.game_config is not None:
        game_config = payload.game_config.dump()
        cards = (await db.execute(select(ActionCard))).scalars().all()
        validate_game_config(list(cards), game_config)
        preset.game_config = game_config
    preset.revision += 1
    preset.updated_by_user_id = principal.user_id
    preset.updated_at = datetime.now(UTC)
    await audit(
        db,
        actor_user_id=principal.user_id,
        event_type="round_preset_updated",
        target_type="round_preset",
        target_id=str(preset.id),
        reason=preset.name,
        request_id=getattr(request.state, "request_id", None),
        metadata={"revision_after": preset.revision},
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise Conflict(
            "Пресет с таким названием уже существует.", code="preset_name_taken"
        ) from exc
    await db.refresh(preset)
    return preset_out(preset)


@router.delete(
    "/round-presets/{preset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="admin_preset_delete",
)
async def delete_preset(
    preset_id: int,
    request: Request,
    confirm: bool = Query(default=False),
    principal: CurrentPrincipal = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    preset = await _get_preset(db, preset_id)
    if not confirm:
        raise Conflict(
            "Удаление пресета требует подтверждения.", code="confirmation_required"
        )
    # Rounds keep their own snapshot, so they survive; only the link is cleared.
    await db.execute(
        Round.__table__.update()
        .where(Round.preset_id == preset.id)
        .values(preset_id=None)
    )
    await audit(
        db,
        actor_user_id=principal.user_id,
        event_type="round_preset_deleted",
        target_type="round_preset",
        target_id=str(preset.id),
        reason=preset.name,
        request_id=getattr(request.state, "request_id", None),
    )
    await db.delete(preset)
    await db.commit()
