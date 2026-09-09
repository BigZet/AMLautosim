"""DB-free semantic validation shared by file and HTTP configuration paths."""

from __future__ import annotations

from typing import Any

from src.aml_workshop_simulator.domain.game_models import RULESET_VERSION, CardSpec
from src.aml_workshop_simulator.domain.round_policy import (
    MAX_VISIBLE_PARAMS,
    declared_params,
)
from src.aml_workshop_simulator.domain.scoring import (
    LEADERBOARD_VERSION,
    SCORING_VERSION,
    weights_sum_to_one,
)

SUPPORTED_RULESETS = {RULESET_VERSION}
SUPPORTED_SCORING = {SCORING_VERSION}
SUPPORTED_LEADERBOARD = {LEADERBOARD_VERSION}


def validate_config_against_catalog(
    available: dict[tuple[str, int], CardSpec], game_config: dict[str, Any]
) -> None:
    """Validate a new round against its available cards; raise ValueError on failure."""
    ruleset = game_config.get("ruleset_version")
    if ruleset not in SUPPORTED_RULESETS:
        raise ValueError(
            f"Версия правил «{ruleset}» отсутствует в этой сборке. "
            f"Доступны: {', '.join(sorted(SUPPORTED_RULESETS))}."
        )
    scoring_version = (game_config.get("scoring") or {}).get("version")
    if scoring_version not in SUPPORTED_SCORING:
        raise ValueError(
            f"Версия скоринга «{scoring_version}» отсутствует в этой сборке."
        )
    board_version = (game_config.get("leaderboard") or {}).get("version")
    if board_version not in SUPPORTED_LEADERBOARD:
        raise ValueError(
            f"Версия лидерборда «{board_version}» отсутствует в этой сборке."
        )
    if not weights_sum_to_one(game_config):
        raise ValueError("Веса лидерборда должны в сумме давать 1.")

    from pydantic import ValidationError

    from src.aml_workshop_simulator.schemas.round_config import GameConfigIn

    try:
        GameConfigIn.model_validate(game_config)
    except ValidationError as error:
        raise ValueError(str(error)) from error
    operations = game_config.get("operations") or []
    if not operations:
        raise ValueError("Не указана ни одна операция для раунда.")

    for entry in operations:
        key = (str(entry.get("code")), int(entry.get("version", 1)))
        card = available.get(key)
        if card is None:
            raise ValueError(
                f"Операция «{key[0]}» версии {key[1]} не найдена или неактивна."
            )
        spec = card
        allowed = set(declared_params(spec))
        visible = list(entry.get("visible_params") or [])
        if len(visible) > MAX_VISIBLE_PARAMS:
            raise ValueError(
                f"Операция «{spec.title}»: показать можно не более "
                f"{MAX_VISIBLE_PARAMS} параметров, выбрано {len(visible)}."
            )
        unknown = [param for param in visible if param not in allowed]
        if unknown:
            raise ValueError(
                f"Операция «{spec.title}»: параметр {', '.join(unknown)} не объявлен "
                "этой карточкой."
            )
        for param, value in (entry.get("defaults") or {}).items():
            if param not in allowed:
                raise ValueError(
                    f"Операция «{spec.title}»: значение по умолчанию задано для "
                    f"неизвестного параметра «{param}»."
                )
            if param in visible:
                raise ValueError(
                    f"Операция «{spec.title}»: закрепить можно только скрытый параметр «{param}»."
                )
            field = spec.field_spec(param)
            if field and field.get("kind") == "toggle" and not isinstance(value, bool):
                raise ValueError(
                    f"Операция «{spec.title}»: «{param}» должен быть true или false."
                )
            options = _param_options(spec, param)
            if options and value not in options:
                raise ValueError(
                    f"Операция «{spec.title}», параметр «{param}»: значение "
                    f"«{value}» недопустимо."
                )
        _validate_overrides(spec, entry)


def _param_options(spec: CardSpec, param: str) -> list[Any]:
    field = spec.field_spec(param)
    if not field:
        return []
    return [option["value"] for option in field.get("options", [])]


def _validate_overrides(spec: CardSpec, entry: dict[str, Any]) -> None:
    from decimal import Decimal

    minimum = entry.get("min_amount", spec.min_amount)
    maximum = entry.get("max_amount", spec.max_amount)
    if (
        minimum is not None
        and maximum is not None
        and Decimal(str(minimum)) > Decimal(str(maximum))
    ):
        raise ValueError(
            f"Операция «{spec.title}»: минимальная сумма больше максимальной."
        )
