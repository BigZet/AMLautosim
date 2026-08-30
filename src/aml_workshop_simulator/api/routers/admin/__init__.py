"""Administrator API.

Split into one module per concern so each file stays readable:

* `rounds`       — card catalogue, round configuration and the lifecycle
                   (`start` / `stop` / `restart` / `score`);
* `presets`      — reusable round configurations;
* `participants` — the inspector: identities, sessions, draft history;
* `leaderboard`  — manual overlays and the administrator board;
* `audit`        — the trail every command writes.
"""

from fastapi import APIRouter

from aml_workshop_simulator.api.routers.admin import (
    audit,
    leaderboard,
    participants,
    presets,
    rounds,
)
from aml_workshop_simulator.api.routers.admin.common import (
    config_version,
    round_out,
    validate_game_config,
)

router = APIRouter()
router.include_router(rounds.router)
router.include_router(presets.router)
router.include_router(participants.router)
router.include_router(leaderboard.router)
router.include_router(audit.router)

__all__ = ["config_version", "round_out", "router", "validate_game_config"]
