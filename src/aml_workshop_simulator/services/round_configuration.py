"""Shared helpers of the administrator API."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.aml_workshop_simulator.core.errors import Conflict
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
        closed_at=round_obj.closed_at,
        scoring_started_at=round_obj.scoring_started_at,
        scoring_error=round_obj.scoring_error,
        completed_at=round_obj.completed_at,
    )


def config_version(game_config: dict[str, Any]) -> str:
    payload = {
        key: value for key, value in game_config.items() if key != "config_version"
    }
    blob = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return f"round-config-v5:sha256:{hashlib.sha256(blob.encode('utf-8')).hexdigest()}"


def _config_error(message: str) -> Conflict:
    return Conflict(message, code="round_configuration_invalid")


def validate_game_config(
    db_cards: list[ActionCard], game_config: dict[str, Any]
) -> None:
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

    from pydantic import ValidationError

    from src.aml_workshop_simulator.schemas.round_config import GameConfigIn

    try:
        GameConfigIn.model_validate(game_config)
    except ValidationError as error:
        raise _config_error(str(error)) from error
    available = {
        (card.code, card.version): card_spec_from_row(card)
        for card in db_cards
        if card.is_active
    }
    operations = game_config.get("operations") or []
    if not operations:
        raise _config_error("Не указана ни одна операция для раунда.")

    for entry in operations:
        key = (str(entry.get("code")), int(entry.get("version", 1)))
        card = available.get(key)
        if card is None:
            raise _config_error(
                f"Операция «{key[0]}» версии {key[1]} не найдена или неактивна."
            )
        spec = card
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
            if param in visible:
                raise _config_error(
                    f"Операция «{spec.title}»: закрепить можно только скрытый параметр «{param}»."
                )
            field = spec.field_spec(param)
            if field and field.get("kind") == "toggle" and not isinstance(value, bool):
                raise _config_error(
                    f"Операция «{spec.title}»: «{param}» должен быть true или false."
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

    minimum = entry.get("min_amount", spec.min_amount)
    maximum = entry.get("max_amount", spec.max_amount)
    if minimum is not None and maximum is not None:
        if Decimal(str(minimum)) > Decimal(str(maximum)):
            raise _config_error(
                f"Операция «{spec.title}»: минимальная сумма больше максимальной."
            )
