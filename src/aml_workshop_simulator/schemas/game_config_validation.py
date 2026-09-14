"""DB-free semantic validation shared by file and HTTP configuration paths."""

from __future__ import annotations

from typing import Any

from src.aml_workshop_simulator.domain.game_models import RULESET_VERSION, CardSpec
from src.aml_workshop_simulator.domain.round_policy import (
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


class ConfigurationViolation(ValueError):
    """Semantic error with a stable path for an independent configuration UI."""

    def __init__(self, message: str, field: str, reason: str = "configuration_invalid"):
        super().__init__(message)
        self.violations = [{"field": field, "reason": reason, "message": message}]


def validate_config_against_catalog(
    available: dict[tuple[str, int], CardSpec], game_config: dict[str, Any]
) -> None:
    """Validate a new round against its available cards; raise ValueError on failure."""
    ruleset = game_config.get("ruleset_version")
    if ruleset not in SUPPORTED_RULESETS:
        raise ConfigurationViolation(
            f"Версия правил «{ruleset}» отсутствует в этой сборке. "
            f"Доступны: {', '.join(sorted(SUPPORTED_RULESETS))}.",
            "game_config.ruleset_version",
            "unsupported_version",
        )
    scoring_version = (game_config.get("scoring") or {}).get("version")
    if scoring_version not in SUPPORTED_SCORING:
        raise ConfigurationViolation(
            f"Версия скоринга «{scoring_version}» отсутствует в этой сборке.",
            "game_config.scoring.version",
            "unsupported_version",
        )
    board_version = (game_config.get("leaderboard") or {}).get("version")
    if board_version not in SUPPORTED_LEADERBOARD:
        raise ConfigurationViolation(
            f"Версия лидерборда «{board_version}» отсутствует в этой сборке.",
            "game_config.leaderboard.version",
            "unsupported_version",
        )
    if not weights_sum_to_one(game_config):
        raise ConfigurationViolation(
            "Веса лидерборда должны в сумме давать 1.",
            "game_config.leaderboard.weights",
        )

    from pydantic import ValidationError

    from src.aml_workshop_simulator.schemas.round_config import parse_game_config

    try:
        parse_game_config(game_config)
    except ValidationError as error:
        raise ValueError(str(error)) from error
    operations = game_config.get("operations") or []
    if not operations:
        raise ValueError("Не указана ни одна операция для раунда.")

    for index, entry in enumerate(operations):
        path = f"game_config.operations.{index}"
        key = (str(entry.get("code")), int(entry.get("version", 1)))
        card = available.get(key)
        if card is None:
            raise ConfigurationViolation(
                f"Операция «{key[0]}» версии {key[1]} не найдена или неактивна.",
                f"{path}.code",
                "card_unavailable",
            )
        spec = card
        allowed = set(declared_params(spec))
        visible = list(entry.get("visible_params") or [])
        unknown = [param for param in visible if param not in allowed]
        if unknown:
            raise ConfigurationViolation(
                f"Операция «{spec.title}»: параметр {', '.join(unknown)} не объявлен "
                "этой карточкой.",
                f"{path}.visible_params",
                "unknown_parameter",
            )
        _validate_overrides(spec, entry, path)


def _validate_overrides(spec: CardSpec, entry: dict[str, Any], path: str) -> None:
    from decimal import Decimal

    minimum = entry.get("min_amount", spec.min_amount)
    maximum = entry.get("max_amount", spec.max_amount)
    if (
        minimum is not None
        and maximum is not None
        and Decimal(str(minimum)) > Decimal(str(maximum))
    ):
        raise ConfigurationViolation(
            f"Операция «{spec.title}»: минимальная сумма больше максимальной.",
            f"{path}.min_amount",
            "inverted_range",
        )
