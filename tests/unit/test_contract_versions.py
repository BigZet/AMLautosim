"""Golden v7 calculations plus explicit read-only v8 foundation."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.aml_workshop_simulator.core.errors import Conflict, ValidationFailed
from src.aml_workshop_simulator.domain.contract_versions import (
    require_playable_contract,
)
from src.aml_workshop_simulator.domain.rules import evaluate_scenario, submit_blockers
from src.aml_workshop_simulator.domain.scoring import (
    leaderboard_scores,
    resource_score,
    score_scenario,
)
from src.aml_workshop_simulator.schemas.expanded_contract import ExpandedScenarioStepIn
from src.aml_workshop_simulator.schemas.round_config import (
    ExpandedGameConfigIn,
    GameConfigIn,
    parse_game_config,
)
from src.aml_workshop_simulator.services.configuration import snapshot_specs
from src.aml_workshop_simulator.services.editor_metadata import editor_metadata

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/contracts"
GOLDEN = json.loads((FIXTURES / "legacy-v7.json").read_text())


def expanded_config():
    config = deepcopy(GOLDEN["config"])
    config.pop("card_snapshots")
    config["schema_version"] = 8
    config["behavior"] = json.loads(
        (FIXTURES / "expanded-v8-behavior.json").read_text()
    )
    return config


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=lambda c: c["name"])
def test_legacy_golden(case):
    config = deepcopy(GOLDEN["config"])
    specs = snapshot_specs(config)
    snap = evaluate_scenario(case["steps"], specs, config)
    score = score_scenario(case["steps"], specs, config)
    board = leaderboard_scores(
        score["risk_score"], resource_score(snap, config), config
    )
    assert snap == case["snapshot"]
    assert submit_blockers(snap) == case["blockers"]
    assert json.loads(json.dumps(score, default=str)) == case["scoring"]
    assert json.loads(json.dumps(board, default=str)) == case["leaderboard"]
    assert config == GOLDEN["config"]


def test_expanded_typed_roundtrip_and_legacy_unchanged():
    model = parse_game_config(expanded_config())
    assert isinstance(model, ExpandedGameConfigIn)
    dumped = model.dump()
    assert parse_game_config(json.loads(json.dumps(dumped))).dump() == dumped
    assert dumped["behavior"]["history"]["operations"][0]["amount"] == "25000.50"
    assert dumped["behavior"]["timeline"]["waiting_costs"]["1440"] == 4
    legacy = deepcopy(GOLDEN["config"])
    legacy.pop("card_snapshots")
    parsed = parse_game_config(legacy)
    assert type(parsed) is GameConfigIn
    assert "behavior" not in parsed.dump()
    legacy.pop("schema_version")
    assert parse_game_config(legacy).schema_version == 7
    assert editor_metadata().schema_version == 8


@pytest.mark.parametrize(
    "field", ["counterparties", "profile", "history", "timeline", "turnover"]
)
def test_incomplete_expanded_config_rejected(field):
    config = expanded_config()
    del config["behavior"][field]
    with pytest.raises(ValidationError):
        parse_game_config(config)


@pytest.mark.parametrize("version", [6, 9, "8", None, True])
def test_unknown_versions_never_fall_back(version):
    config = deepcopy(GOLDEN["config"])
    config["schema_version"] = version
    for operation in [parse_game_config, snapshot_specs, require_playable_contract]:
        with pytest.raises(ValidationFailed) as error:
            operation(config)
        assert error.value.code == "round_contract_unsupported"
    with pytest.raises(ValidationFailed):
        evaluate_scenario([], {}, config)
    with pytest.raises(ValidationFailed):
        score_scenario([], {}, config)


def test_expanded_cannot_run_legacy_engine():
    config = expanded_config()
    for operation in [
        lambda: require_playable_contract(config),
        lambda: evaluate_scenario([], {}, config),
        lambda: score_scenario([], {}, config),
    ]:
        with pytest.raises(Conflict) as error:
            operation()
        assert error.value.code == "round_contract_not_ready"


def test_unknown_history_is_not_observed_empty_history():
    config = expanded_config()
    config["behavior"]["history"]["operations"] = None
    assert parse_game_config(config).dump()["behavior"]["history"]["operations"] is None
    config["behavior"]["history"]["operations"] = []
    assert parse_game_config(config).dump()["behavior"]["history"]["operations"] == []


def test_reserved_steps_reject_manual_derived_context():
    step = deepcopy(GOLDEN["cases"][0]["steps"][0])
    step["context"] = {"channel": "bank"}
    step.update(sender_id="A", interval_minutes=10)
    model = ExpandedScenarioStepIn.model_validate(step)
    assert ExpandedScenarioStepIn.model_validate_json(model.model_dump_json()) == model
    step["context"]["velocity"] = "rapid"
    with pytest.raises(ValidationError):
        ExpandedScenarioStepIn.model_validate(step)


def test_expanded_requires_explicit_version_even_at_api_boundary():
    from src.aml_workshop_simulator.schemas.admin import RoundCreateIn

    config = expanded_config()
    del config["schema_version"]
    with pytest.raises(ValidationError):
        RoundCreateIn.model_validate({"title": "Test round", "game_config": config})
