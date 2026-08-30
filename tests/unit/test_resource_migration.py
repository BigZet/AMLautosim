"""Regression coverage for retiring the old gameplay resource contract."""

from copy import deepcopy
from decimal import Decimal
from importlib import import_module

import pytest
from pydantic import ValidationError

from aml_workshop_simulator.domain.rules import REFERENCE_GAME_CONFIG
from aml_workshop_simulator.schemas.round_config import GameConfigIn

migration = import_module(
    "migrations.versions.e84a6d2c190f_remove_trust_and_rename_available_steps"
)


def legacy_config() -> dict:
    config = deepcopy(REFERENCE_GAME_CONFIG)
    config["schema_version"] = 3
    config["ruleset_version"] = "game-rules-v2"
    config["config_version"] = "old-hash"
    config["resources"]["initial_trust"] = 100
    config["operations"][0]["trust_cost"] = 5
    config["leaderboard"]["version"] = "leaderboard-v1"
    config["leaderboard"]["resource_weights"] = {
        "balance": "0.20",
        "energy": "0.15",
        "time": "0.15",
        "trust": "0.25",
        "fees": "0.15",
        "slots": "0.10",
    }
    return config


def test_legacy_configuration_migrates_to_the_current_contract() -> None:
    original = legacy_config()
    migrated = migration.migrate_config(original)
    GameConfigIn.model_validate(migrated)
    assert original["resources"]["initial_trust"] == 100
    assert migrated["config_version"].startswith("round-config-v4:sha256:")
    assert migrated["leaderboard"] == REFERENCE_GAME_CONFIG["leaderboard"]
    assert "initial_trust" not in migrated["resources"]
    assert "trust_cost" not in migrated["operations"][0]
    assert migration.migrate_config(migrated) == migrated


def test_custom_weights_are_preserved_proportionally() -> None:
    config = legacy_config()
    config["leaderboard"]["resource_weights"] = {
        "balance": "0.50", "trust": "0.25", "slots": "0.25",
    }
    weights = migration.migrate_config(config)["leaderboard"]["resource_weights"]
    assert weights == {
        "balance": "0.67", "energy": "0.00", "time": "0.00",
        "fees": "0.00", "available_steps": "0.33",
    }
    assert sum(map(Decimal, weights.values())) == Decimal(1)


@pytest.mark.parametrize("keep_balance_violation", [False, True])
def test_old_resource_violations_are_removed_without_hiding_other_errors(
    keep_balance_violation,
) -> None:
    violations = [{"reason": "insufficient_trust", "message": "старое ограничение"}]
    if keep_balance_violation:
        violations.append({"reason": "insufficient_balance", "message": "не хватает денег"})
    original = {
        "schema_version": 3,
        "ruleset_version": "game-rules-v2",
        "valid": False,
        "resources_after": {"balance": "100.00", "trust": -1, "slots": 6},
        "violations": violations,
        "per_step": [{
            "trust_cost": 101, "trust_after": -1,
            "resources_before": {"trust": 100, "energy": 14},
            "resources_after": {"trust": -1, "energy": 13},
        }],
    }
    result = migration.migrate_snapshot(original)
    assert result["valid"] is (not keep_balance_violation)
    assert len(result["violations"]) == int(keep_balance_violation)
    assert result["resources_after"] == {"balance": "100.00", "available_steps": 6}
    assert result["per_step"] == [{
        "resources_before": {"energy": 14}, "resources_after": {"energy": 13},
    }]
    assert result["schema_version"] == 4
    assert result["ruleset_version"] == "game-rules-v3"


def test_parameter_risk_and_other_costs_survive_cleanup() -> None:
    schema = {"fields": [{"options": [{"trust_cost": 7, "risk_points": 12, "energy_cost": 1}]}]}
    assert migration.clean_resources(schema) == {
        "fields": [{"options": [{"risk_points": 12, "energy_cost": 1}]}],
    }


@pytest.mark.parametrize("legacy_field", ["initial_trust", "trust_cost", "slots"])
def test_new_requests_cannot_reintroduce_removed_fields(legacy_field) -> None:
    config = deepcopy(REFERENCE_GAME_CONFIG)
    if legacy_field == "initial_trust":
        config["resources"][legacy_field] = 100
    elif legacy_field == "trust_cost":
        config["operations"][0][legacy_field] = 10
    else:
        weights = config["leaderboard"]["resource_weights"]
        weights[legacy_field] = weights.pop("available_steps")
    with pytest.raises(ValidationError):
        GameConfigIn.model_validate(config)
