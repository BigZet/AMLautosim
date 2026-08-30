"""Shared helpers of the administrator API."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.api.errors import Conflict, NotFound, ValidationFailed
from src.aml_workshop_simulator.db.models.action_cards import ActionCard
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.domain.round_policy import (
    MAX_VISIBLE_PARAMS,
    declared_params,
)
from src.aml_workshop_simulator.domain.rules import RULESET_VERSION, card_spec_from_row
from src.aml_workshop_simulator.domain.scoring import (
    LEADERBOARD_VERSION,
    SCORING_VERSION,
    weights_sum_to_one,
)
from src.aml_workshop_simulator.schemas.admin import RoundAdminOut
from src.aml_workshop_simulator.services.audit import record_event

SUPPORTED_RULESETS = {RULESET_VERSION}
SUPPORTED_SCORING = {SCORING_VERSION}
SUPPORTED_LEADERBOARD = {LEADERBOARD_VERSION}

#: Statuses a round can be in, and the transitions the API accepts.
ROUND_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"active"},
    "active": {"stopped", "scoring"},
    "stopped": {"active", "scoring"},
    "scoring": {"completed"},
    "completed": set(),
}

ROUND_STATUS_LABELS = {
    "draft": "черновик",
    "active": "идет",
    "stopped": "остановлен",
    "scoring": "подсчет результатов",
    "completed": "завершен",
}


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
        stopped_at=round_obj.stopped_at,
        completed_at=round_obj.completed_at,
        restarted_from_round_id=round_obj.restarted_from_round_id,
        preset_id=round_obj.preset_id,
    )


def config_version(game_config: dict[str, Any]) -> str:
    payload = {key: value for key, value in game_config.items() if key != "config_version"}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return f"round-config-v4:sha256:{hashlib.sha256(blob.encode('utf-8')).hexdigest()}"


async def get_round(db: AsyncSession, round_id: int) -> Round:
    round_obj = (
        await db.execute(select(Round).where(Round.id == round_id))
    ).scalars().first()
    if round_obj is None:
        raise NotFound("Раунд не найден.", code="round_not_found")
    return round_obj


async def audit(
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
    """Admin-side alias of `services.audit.record_event`."""
    await record_event(
        db,
        actor_user_id=actor_user_id,
        event_type=event_type,
        round_id=round_id,
        scenario_id=scenario_id,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        request_id=request_id,
        idempotency_key_hash=idempotency_key_hash,
        metadata=metadata,
    )


def _config_error(message: str) -> Conflict:
    return Conflict(message, code="round_configuration_invalid")


def validate_game_config(db_cards: list[ActionCard], game_config: dict[str, Any]) -> None:
    """Check a stored snapshot against this build and the live card catalog."""
    ruleset = game_config.get("ruleset_version")
    if ruleset not in SUPPORTED_RULESETS:
        raise _config_error(
            f"Версия правил «{ruleset}» отсутствует в этой сборке. "
            f"Доступны: {', '.join(sorted(SUPPORTED_RULESETS))}."
        )
    scoring_version = (game_config.get("scoring") or {}).get("version")
    if scoring_version not in SUPPORTED_SCORING:
        raise _config_error(
            f"Версия скоринга «{scoring_version}» отсутствует в этой сборке."
        )
    board_version = (game_config.get("leaderboard") or {}).get("version")
    if board_version not in SUPPORTED_LEADERBOARD:
        raise _config_error(
            f"Версия лидерборда «{board_version}» отсутствует в этой сборке."
        )
    if not weights_sum_to_one(game_config):
        raise _config_error("Веса лидерборда должны в сумме давать 1.")

    available = {(card.code, card.version): card for card in db_cards if card.is_active}
    operations = game_config.get("operations") or []
    refs = game_config.get("card_versions") or []
    if not operations and not refs:
        raise _config_error("Не указана ни одна операция для раунда.")

    for ref in refs:
        key = (str(ref.get("code")), int(ref.get("version", 0)))
        card = available.get(key)
        if card is None:
            raise _config_error(
                f"Карточка «{key[0]}» версии {key[1]} не найдена или неактивна."
            )
        if int(ref.get("id", card.id)) != card.id:
            raise _config_error(
                f"Идентификатор карточки «{key[0]}» не совпадает с каталогом."
            )

    for entry in operations:
        key = (str(entry.get("code")), int(entry.get("version", 1)))
        card = available.get(key)
        if card is None:
            raise _config_error(
                f"Операция «{key[0]}» версии {key[1]} не найдена или неактивна."
            )
        spec = card_spec_from_row(card)
        allowed = set(declared_params(spec))
        visible = list(entry.get("visible_params") or [])
        if len(visible) > MAX_VISIBLE_PARAMS:
            raise _config_error(
                f"Операция «{spec.title}»: показать можно не более "
                f"{MAX_VISIBLE_PARAMS} параметров, выбрано {len(visible)}."
            )
        unknown = [param for param in visible if param not in allowed]
        if unknown:
            raise _config_error(
                f"Операция «{spec.title}»: параметр {', '.join(unknown)} не объявлен "
                "этой карточкой."
            )
        for param, value in (entry.get("defaults") or {}).items():
            if param not in allowed:
                raise _config_error(
                    f"Операция «{spec.title}»: значение по умолчанию задано для "
                    f"неизвестного параметра «{param}»."
                )
            options = _param_options(spec, param)
            if options and value not in options:
                raise _config_error(
                    f"Операция «{spec.title}», параметр «{param}»: значение "
                    f"«{value}» недопустимо."
                )
        _validate_overrides(spec, entry)


def _param_options(spec: Any, param: str) -> list[Any]:
    field = spec.field_spec(param)
    if not field:
        return []
    return [option["value"] for option in field.get("options", [])]


def _validate_overrides(spec: Any, entry: dict[str, Any]) -> None:
    from decimal import Decimal

    minimum = entry.get("min_amount")
    maximum = entry.get("max_amount")
    if minimum is not None and maximum is not None:
        if Decimal(str(minimum)) > Decimal(str(maximum)):
            raise _config_error(
                f"Операция «{spec.title}»: минимальная сумма больше максимальной."
            )
    frequency = entry.get("max_frequency")
    round_limit = entry.get("round_frequency_limit")
    if frequency is not None and round_limit is not None:
        if int(round_limit) < int(frequency):
            raise _config_error(
                f"Операция «{spec.title}»: лимит повторов за раунд меньше лимита "
                "повторов одного шага."
            )
    if not entry.get("show_frequency", True):
        # A pinned frequency of one must still be inside the card's own range.
        if frequency is not None and int(frequency) < 1:
            raise _config_error(
                f"Операция «{spec.title}»: лимит повторов не может быть меньше 1."
            )


def require_confirmation(confirmed: bool, action: str) -> None:
    if confirmed:
        return
    raise ValidationFailed(
        f"Действие «{action}» требует подтверждения.",
        code="confirmation_required",
        details={
            "violations": [
                {
                    "field": "confirm",
                    "reason": "confirmation_required",
                    "message": (
                        f"Подтвердите действие «{action}»: установите confirm = true."
                    ),
                }
            ]
        },
    )
