"""Game invariants without PostgreSQL or HTTP."""

from copy import deepcopy
from uuid import uuid4

import pytest

from src.aml_workshop_simulator.core.game_config import base_game_config
from src.aml_workshop_simulator.domain.catalog import CARD_CATALOG
from src.aml_workshop_simulator.domain.game_models import card_spec_from_catalog
from src.aml_workshop_simulator.domain.round_policy import RoundPolicy
from src.aml_workshop_simulator.domain.simulation import (
    evaluate_scenario,
    submit_blockers,
)
from src.aml_workshop_simulator.schemas.scenarios import ScenarioStepIn
from src.aml_workshop_simulator.services.scenario_service import (
    canonical_steps,
    payload_hash,
)


@pytest.fixture
def game():
    config = deepcopy(base_game_config())
    # Fixed mechanics fixture; production balance has its own playthrough checks.
    config["resources"] = {
        "initial_balance": "250000.00",
        "initial_energy": 14,
        "initial_time": 18,
    }
    config["objectives"] = {"target_outflow": "150000.00", "max_actions": 8}
    config["constraints"]["max_identical_steps"] = 3
    config["constraints"]["category_limits"]["cash"] = "150000.00"
    for operation in config["operations"]:
        if operation["code"] == "cash_withdrawal":
            operation["max_occurrences"] = 3
            operation["visible_params"] = ["channel", "context.time_of_day"]

    specs = {
        s.key: s
        for i, entry in enumerate(CARD_CATALOG, 1)
        if (s := card_spec_from_catalog(entry, i))
    }
    card = next(s for s in specs.values() if s.code == "cash_withdrawal")
    policy = RoundPolicy.from_config(config, specs)
    inputs = [
        ScenarioStepIn.model_validate(
            {
                "step_id": str(uuid4()),
                "card": {"id": card.id, "code": card.code, "version": card.version},
                "amount": "50000",
                "action_details": {f["key"]: f["default"] for f in card.fields},
            }
        )
        for _ in range(3)
    ]
    return config, specs, canonical_steps(inputs, specs, policy)


def test_three_cards_are_three_operations(game):
    config, specs, steps = game
    snapshot = evaluate_scenario(steps, specs, config)
    assert snapshot["valid"] and snapshot["objective"]["reached"]
    assert snapshot["totals"] == {
        "gross_inflow": "0.00",
        "gross_outflow": "150000.00",
        "fees": "1500.00",
    }
    assert snapshot["resources_after"]["balance"] == "98500.00"
    assert snapshot["resources_after"]["available_steps"] == 5
    assert len(snapshot["per_step"]) == 3
    assert not submit_blockers(snapshot)


@pytest.mark.parametrize(
    "section,key,value,reason",
    [
        ("resources", "initial_balance", "1000.00", "insufficient_balance"),
        ("resources", "initial_energy", 0, "insufficient_energy"),
        ("resources", "initial_time", 0, "insufficient_time"),
        ("objectives", "max_actions", 2, "max_actions_exceeded"),
        ("constraints", "max_identical_steps", 2, "identical_streak_exceeded"),
        (
            "constraints",
            "category_limits",
            {"cash": "100000.00"},
            "category_limit_exceeded",
        ),
    ],
)
def test_limits_block_submission(game, section, key, value, reason):
    config, specs, steps = game
    config[section][key] = value
    snapshot = evaluate_scenario(steps, specs, config)
    assert not snapshot["valid"]
    assert reason in {v["reason"] for v in submit_blockers(snapshot)}


def test_empty_and_incomplete_objective(game):
    config, specs, steps = game
    assert {
        v["reason"] for v in submit_blockers(evaluate_scenario([], specs, config))
    } == {
        "scenario_empty",
        "target_outflow_not_reached",
    }
    one = evaluate_scenario(steps[:1], specs, config)
    assert one["valid"] and not one["objective"]["reached"]
    assert {v["reason"] for v in submit_blockers(one)} == {"target_outflow_not_reached"}


def test_night_limit(game):
    config, specs, steps = game
    for step in steps:
        step["context"]["time_of_day"] = "night"
    snapshot = evaluate_scenario(steps, specs, config)
    assert "night_operations_exceeded" in {v["reason"] for v in snapshot["violations"]}


def test_hash_ignores_object_key_order_but_preserves_chain_order(game):
    _, _, steps = game
    reordered_keys = [{key: step[key] for key in reversed(step)} for step in steps]
    assert payload_hash(steps) == payload_hash(reordered_keys)
    assert payload_hash(steps) != payload_hash(list(reversed(steps)))
