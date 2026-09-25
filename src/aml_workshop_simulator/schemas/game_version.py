"""Versions supported by new-game HTTP commands."""

from enum import IntEnum

from src.aml_workshop_simulator.core.errors import ValidationFailed


class GameVersion(IntEnum):
    current = 10


def require_game_version(value: int) -> GameVersion:
    if type(value) is not int and not isinstance(value, GameVersion):
        raise ValidationFailed("Версия игры должна быть 10.")
    try:
        return GameVersion(value)
    except ValueError as exc:
        raise ValidationFailed("Версия игры должна быть 10.") from exc
