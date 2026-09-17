"""One current game: configure, start, score, reset. No round history."""

from datetime import UTC, datetime

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.core.errors import Conflict
from src.aml_workshop_simulator.services.game_classifier import game_config
from src.aml_workshop_simulator.db.models.action_cards import ActionCard
from src.aml_workshop_simulator.db.models.audit_events import AuditEvent
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.db.models.scoring_results import ScoringResult
from src.aml_workshop_simulator.db.queries import get_round
from src.aml_workshop_simulator.domain.contract_versions import (
    require_playable_contract,
    require_new_round_allowed,
)
from src.aml_workshop_simulator.domain.lifecycle import require_round_status
from src.aml_workshop_simulator.schemas.admin import (
    RoundAdminOut,
    RoundCreateIn,
    RoundUpdateIn,
)
from src.aml_workshop_simulator.schemas.round_config import (
    parse_game_config,
    RoundConfigInput,
)
from src.aml_workshop_simulator.services.audit import record_event
from src.aml_workshop_simulator.services.configuration import freeze_game_config
from src.aml_workshop_simulator.services.round_configuration import (
    config_version,
    round_out,
)


async def prepare_config(
    db: AsyncSession, config: RoundConfigInput | None = None, *, new_round: bool = True
) -> dict:
    value = (config or parse_game_config(game_config())).dump()
    require_playable_contract(value)
    if new_round and value.get("behavior", {}).get("release") is not None:
        require_new_round_allowed(value)
    cards = list(
        (await db.execute(select(ActionCard).where(ActionCard.is_active)))
        .scalars()
        .all()
    )
    frozen = freeze_game_config(value, cards)
    from src.aml_workshop_simulator.services.model_scoring import get_round_scorer

    scorer = get_round_scorer(frozen)
    scorer.check_config(frozen)
    frozen["risk_model"] = (
        scorer.pin_identity(frozen)
        if frozen["schema_version"] == 10
        else scorer.identity.copy()
    )
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
    require_playable_contract(row.game_config)
    if (
        payload.game_config is not None
        and (
            row.game_config.get("behavior", {}).get("release") is not None
            or getattr(getattr(payload.game_config, "behavior", None), "release", None)
            is not None
        )
        and (
            row.game_config["schema_version"] != payload.game_config.schema_version
            or row.game_config.get("behavior", {}).get("release")
            != getattr(getattr(payload.game_config, "behavior", None), "release", None)
        )
    ):
        raise Conflict(
            "Версию правил выбирают при создании новой игры.",
            code="round_contract_immutable",
        )
    new_config = (
        await prepare_config(db, payload.game_config, new_round=False)
        if payload.game_config is not None
        else None
    )
    if payload.title is not None:
        row.title = payload.title
    if new_config is not None:
        row.game_config = new_config
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
    require_playable_contract(row.game_config)
    if row.status == "active":
        return round_out(row)
    require_round_status(row.status, "draft")
    require_new_round_allowed(row.game_config)
    from src.aml_workshop_simulator.services.model_scoring import get_round_scorer

    get_round_scorer(row.game_config).check_config(row.game_config, require_pin=True)
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
    db: AsyncSession,
    round_id: int,
    actor_id: int,
    request_id: str | None,
    schema_version: int = 10,
) -> RoundAdminOut:
    await db.execute(text("SELECT pg_advisory_xact_lock(73419001)"))
    row = await get_round(db, round_id, lock="update")
    from src.aml_workshop_simulator.core.expanded_game import expanded_game_config
    from src.aml_workshop_simulator.schemas.round_config import parse_game_config

    if schema_version not in (8, 10):
        raise Conflict("Версия игры не поддерживается.", code="model_contract_mismatch")
    selected = parse_game_config(
        expanded_game_config() if schema_version == 8 else game_config()
    )
    config = await prepare_config(db, selected)
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
