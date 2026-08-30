"""Remove the trust resource and rename slots to available steps.

Stored drafts remain usable; published scoring results and audit events stay
historical records and are not recalculated. Back up the database before this
irreversible data migration.

Revision ID: e84a6d2c190f
Revises: c73f5a1e9d04
Create Date: 2026-08-30
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from decimal import ROUND_FLOOR, Decimal
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "e84a6d2c190f"
down_revision: str | None = "c73f5a1e9d04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RESOURCE_KEYS = ("balance", "energy", "time", "fees", "available_steps")
DEFAULT_WEIGHTS = ("0.27", "0.20", "0.20", "0.20", "0.13")
REMOVED_KEYS = {"trust", "trust_cost", "trust_after", "initial_trust"}


def clean_resources(value: Any) -> Any:
    """Change only retired resource fields, never parameters or risk factors."""
    if isinstance(value, dict):
        return {
            "available_steps" if key == "slots" else key: clean_resources(item)
            for key, item in value.items()
            if key not in REMOVED_KEYS
        }
    if isinstance(value, list):
        return [
            clean_resources(item)
            for item in value
            if not (isinstance(item, dict) and item.get("reason") == "insufficient_trust")
        ]
    return value


def resource_weights(weights: dict[str, Any]) -> dict[str, str]:
    """Preserve remaining relative weights, rounding to cents with sum 1."""
    values = [max(Decimal("0"), Decimal(str(weights.get(key, 0)))) for key in RESOURCE_KEYS]
    total = sum(values)
    if total == 0:
        return dict(zip(RESOURCE_KEYS, DEFAULT_WEIGHTS, strict=True))
    exact = [value * 100 / total for value in values]
    cents = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in exact]
    order = sorted(
        range(len(cents)),
        key=lambda index: (-(exact[index] - cents[index]), index),
    )
    for index in order[:100 - sum(cents)]:
        cents[index] += 1
    return {
        key: f"{Decimal(value) / 100:.2f}"
        for key, value in zip(RESOURCE_KEYS, cents, strict=True)
    }


def migrate_config(value: dict[str, Any]) -> dict[str, Any]:
    config = clean_resources(value)
    config["schema_version"] = 4
    config["ruleset_version"] = "game-rules-v3"
    board = config.setdefault("leaderboard", {})
    board["version"] = "leaderboard-v2"
    board["resource_weights"] = resource_weights(board.get("resource_weights") or {})
    if "config_version" in config:
        config.pop("config_version")
        blob = json.dumps(config, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        config["config_version"] = f"round-config-v4:sha256:{digest}"
    return config


def migrate_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    snapshot = clean_resources(value)
    snapshot["schema_version"] = 4
    snapshot["ruleset_version"] = "game-rules-v3"
    if "violations" in snapshot:
        snapshot["valid"] = not snapshot["violations"]
    return snapshot


def _update_json(
    table_name: str,
    column_name: str,
    transform: Any,
    revision_column: str | None = None,
) -> None:
    columns = [sa.column("id", sa.BigInteger()), sa.column(column_name, sa.JSON())]
    if revision_column:
        columns.append(sa.column(revision_column, sa.Integer()))
    table = sa.table(table_name, *columns)
    connection = op.get_bind()
    for row in connection.execute(sa.select(table)).mappings().all():
        original = row[column_name]
        if original is None:
            continue
        updates = {column_name: transform(original)}
        if revision_column:
            updates[revision_column] = row[revision_column] + 1
        connection.execute(table.update().where(table.c.id == row["id"]).values(**updates))


def upgrade() -> None:
    _update_json("rounds", "game_config", migrate_config, "config_revision")
    _update_json("round_presets", "game_config", migrate_config, "revision")
    _update_json("scenarios", "resource_snapshot", migrate_snapshot)
    _update_json("scenario_versions", "resource_snapshot", migrate_snapshot)
    _update_json("action_cards", "parameter_schema", clean_resources)

    op.drop_constraint("ck_action_cards_costs", "action_cards", type_="check")
    op.drop_column("action_cards", "trust_cost")
    op.create_check_constraint(
        "ck_action_cards_costs", "action_cards", "energy_cost >= 0 AND time_cost >= 0"
    )


def downgrade() -> None:
    raise RuntimeError(
        "This migration removes gameplay data. Restore the pre-upgrade database "
        "backup to return to the previous resource model."
    )
