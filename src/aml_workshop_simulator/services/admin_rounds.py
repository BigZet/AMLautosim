"""One current game: configure, start, score, reset. No round history."""

from datetime import UTC, datetime

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.core.errors import Conflict
from src.aml_workshop_simulator.core.game_config import base_game_config
from src.aml_workshop_simulator.db.models.action_cards import ActionCard
from src.aml_workshop_simulator.db.models.audit_events import AuditEvent
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.db.models.scoring_results import ScoringResult
from src.aml_workshop_simulator.db.queries import get_round
from src.aml_workshop_simulator.domain.lifecycle import require_round_status
from src.aml_workshop_simulator.schemas.admin import (
    RoundAdminOut,
    RoundCreateIn,
    RoundUpdateIn,
)
from src.aml_workshop_simulator.schemas.round_config import GameConfigIn
from src.aml_workshop_simulator.services.audit import record_event
from src.aml_workshop_simulator.services.configuration import freeze_game_config
from src.aml_workshop_simulator.services.round_configuration import (
    config_version,
    round_out,
    validate_game_config,
)


async def prepare_config(db: AsyncSession, config: GameConfigIn | None = None) -> dict:
    value = (config or GameConfigIn.model_validate(base_game_config())).dump()
    cards = list(
        (await db.execute(select(ActionCard).where(ActionCard.is_active)))
        .scalars()
        .all()
    )
    validate_game_config(cards, value)
    frozen = freeze_game_config(value, cards)
    frozen["config_version"] = config_version(frozen)
    return frozen


async def current(db: AsyncSession) -> RoundAdminOut | None:
    row = (await db.execute(select(Round))).scalar_one_or_none()
    return round_out(row) if row else None


async def create(
    db: AsyncSession, payload: RoundCreateIn, actor_id: int, request_id: str | None
) -> RoundAdminOut:
    # Serialize creation even when the singleton row does not exist yet.
    await db.execute(text("SELECT pg_advisory_xact_lock(73419001)"))
    if (await db.execute(select(Round.id))).scalar_one_or_none() is not None:
        raise Conflict(
            "Раунд уже существует. Используйте перезапуск игры.", code="round_exists"
        )
    row = Round(
        title=payload.title,
        status="draft",
        config_revision=1,
        game_config=await prepare_config(db, payload.game_config),
        created_by_user_id=actor_id,
        created_at=datetime.now(UTC),
    )
    db.add(row)
    await db.flush()
    await record_event(
        db,
        actor_user_id=actor_id,
        round_id=row.id,
        event_type="round_created",
        request_id=request_id,
    )
    await db.commit()
    return round_out(row)


async def update_config(
    db: AsyncSession,
    round_id: int,
    payload: RoundUpdateIn,
    actor_id: int,
    request_id: str | None,
) -> RoundAdminOut:
    row = await get_round(db, round_id, lock="update")
    require_round_status(row.status, "draft")
    if row.config_revision != payload.expected_config_revision:
        raise Conflict(
            "Настройки изменены в другом окне. Обновите страницу.",
            code="round_config_revision_conflict",
            details={"current_config_revision": row.config_revision},
        )
    if payload.title is not None:
        row.title = payload.title
    if payload.game_config is not None:
        row.game_config = await prepare_config(db, payload.game_config)
    row.config_revision += 1
    await record_event(
        db,
        actor_user_id=actor_id,
        round_id=row.id,
        event_type="round_config_updated",
        request_id=request_id,
    )
    await db.commit()
    return round_out(row)


async def start(
    db: AsyncSession, round_id: int, actor_id: int, request_id: str | None
) -> RoundAdminOut:
    row = await get_round(db, round_id, lock="update")
    if row.status == "active":
        return round_out(row)
    require_round_status(row.status, "draft")
    row.status = "active"
    row.activated_at = datetime.now(UTC)
    await record_event(
        db,
        actor_user_id=actor_id,
        round_id=row.id,
        event_type="round_started",
        request_id=request_id,
    )
    await db.commit()
    return round_out(row)


async def restart(
    db: AsyncSession, round_id: int, actor_id: int, request_id: str | None
) -> RoundAdminOut:
    await db.execute(text("SELECT pg_advisory_xact_lock(73419001)"))
    row = await get_round(db, round_id, lock="update")
    config = await prepare_config(db)
    # Accounts and authentication sessions survive; all game data is discarded.
    await db.execute(delete(AuditEvent))
    await db.execute(delete(ScoringResult))
    await db.execute(delete(Scenario))
    await db.delete(row)
    await db.flush()
    fresh = Round(
        title="Новая игра",
        status="draft",
        config_revision=1,
        game_config=config,
        created_by_user_id=actor_id,
        created_at=datetime.now(UTC),
    )
    db.add(fresh)
    await db.flush()
    await record_event(
        db,
        actor_user_id=actor_id,
        round_id=fresh.id,
        event_type="round_created",
        request_id=request_id,
    )
    await db.commit()
    return round_out(fresh)
