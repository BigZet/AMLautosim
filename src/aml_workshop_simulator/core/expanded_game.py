"""New-round defaults; every invocation returns a fresh, reproducible snapshot."""

from datetime import datetime
from zoneinfo import ZoneInfo

from .game_config import base_game_config, load_config


def expanded_game_config(starts_at=None):
    config = base_game_config()
    behavior = load_config("expanded_behavior.json")
    zone = ZoneInfo(behavior["timeline"]["timezone"])
    anchor = datetime.fromisoformat(behavior["timeline"]["starts_at"])
    start = starts_at or datetime.now(zone).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    if start.tzinfo is None:
        raise ValueError("Начало сценария требует часового пояса")
    delta = start - anchor
    for event in behavior["history"]["operations"] or []:
        event["occurred_at"] = (
            datetime.fromisoformat(event["occurred_at"]) + delta
        ).isoformat()
    behavior["timeline"]["starts_at"] = start.isoformat()
    config.update(schema_version=8, behavior=behavior)
    config["operations"].append(
        {"code": "purchase", "version": 1, "visible_params": []}
    )
    return config
