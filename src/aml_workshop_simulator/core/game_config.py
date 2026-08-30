"""File-backed game settings. Paths are independent of the working directory.

Files are read once per process; every caller receives its own copy. A missing,
malformed or duplicate-key file is an error, never a reason to invent defaults.
"""

import json
import os
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(
    os.environ.get(
        "AML_GAME_CONFIG_DIR", Path(__file__).resolve().parents[3] / "config"
    )
)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate configuration key: {key}")
        result[key] = value
    return result


@lru_cache
def _read(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
        )
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value
    except (OSError, ValueError) as error:
        raise ValueError(f"Invalid game configuration {path}: {error}") from error


def load_config(name: str) -> dict[str, Any]:
    return deepcopy(_read(name))


def base_game_config() -> dict[str, Any]:
    config = load_config("base_round.json")
    config.setdefault("resource_rules", load_config("resource_rules.json"))
    config["scoring"].setdefault("rules", load_config("risk_rules.json"))
    return config


LIMITS = load_config("limits.json")
