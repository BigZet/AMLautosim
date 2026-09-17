from copy import deepcopy

import pytest

from tests.aml_context_support import context_fixture
from src.aml_workshop_simulator.core.errors import Conflict, ValidationFailed


def test_v10_round_snapshot_roundtrip_preserves_public_context():
    from src.aml_workshop_simulator.schemas.round_config import parse_game_config

    config, _ = context_fixture()
    stored = {**config, "config_version": "test-context-v10"}
    parsed = parse_game_config(stored, stored=True)
    assert parsed.schema_version == 10
    assert parsed.behavior.aml_context.facts[0].verification_status == "verified"
    assert parsed.dump()["behavior"]["aml_context"] == config["behavior"]["aml_context"]


def test_public_contract_rejects_author_truth_and_invalid_fact_references():
    from src.aml_workshop_simulator.schemas.round_config import parse_game_config

    config, _ = context_fixture()
    config.pop("card_snapshots", None)
    config.pop("config_version", None)
    config["behavior"]["aml_context"]["facts"][0]["counterparty_ids"] = ["missing"]
    with pytest.raises(ValueError, match="counterparty"):
        parse_game_config(config)
    config["behavior"]["aml_context"]["facts"][0]["counterparty_ids"] = ["A"]
    config["behavior"]["aml_context"]["author_truth"] = {"aml_label": 1}
    with pytest.raises(ValueError):
        parse_game_config(config)


def test_public_canonicalization_keeps_claims_and_rejects_forgery():
    from src.aml_workshop_simulator.services.counterparties import canonical_expanded_steps

    config, steps = context_fixture()
    result = canonical_expanded_steps(steps, config)
    assert result[0]["claim_id"] == "shared"
    assert result[0]["purpose_code"] == "shared_expense"
    steps[0]["verification_status"] = "verified"
    with pytest.raises(ValidationFailed) as failure:
        canonical_expanded_steps(steps, config)
    assert failure.value.code == "aml_context_invalid"


def test_public_engine_uses_same_resources_as_private_v10_projection():
    from src.aml_workshop_simulator.services.expanded_simulation import evaluate_expanded_scenario
    from src.aml_workshop_simulator.services.aml_context import evaluate

    config, steps = context_fixture()
    before = deepcopy((config, steps))
    assert evaluate_expanded_scenario(steps, config) == evaluate(steps, config)
    assert before == (config, steps)


def test_v10_creation_requires_available_released_package(monkeypatch, tmp_path):
    from src.aml_workshop_simulator.domain.contract_versions import require_new_round_allowed

    config, _ = context_fixture()
    require_new_round_allowed(config)
    monkeypatch.setenv('AML_PROBABILITY_MODEL_PATH', str(tmp_path / 'missing-model'))
    with pytest.raises(Conflict) as failure:
        require_new_round_allowed(config)
    assert failure.value.code == "model_unavailable"


def test_card_projection_keeps_v9_incoming_semantics():
    from src.aml_workshop_simulator.services.configuration import snapshot_specs
    from src.aml_workshop_simulator.services.projections import card_out

    config, _ = context_fixture()
    card = snapshot_specs(config)[("incoming_transfer", 1)]
    public = card_out(card, schema_version=10)
    assert {f.key for f in public.fields} == {"incoming_kind", "bank_country"}
    assert public.context_fields == []


def test_actual_scenario_save_preparation_preserves_context_selection():
    from types import SimpleNamespace
    from src.aml_workshop_simulator.services.scenario_service import prepare_scenario
    from src.aml_workshop_simulator.schemas.scenarios import ScenarioPreviewIn

    config, steps = context_fixture()
    payload = ScenarioPreviewIn(steps=steps)
    canonical, snapshot = prepare_scenario(SimpleNamespace(game_config=config), payload.steps)
    assert canonical[0]["claim_id"] == "shared"
    assert canonical[0]["purpose_code"] == "shared_expense"
    assert snapshot["valid"]


def test_v10_cannot_fall_back_to_deterministic_risk():
    from src.aml_workshop_simulator.services.expanded_simulation import score_expanded_scenario

    config, steps = context_fixture()
    with pytest.raises(ValueError, match="classifier"):
        score_expanded_scenario(steps, config)
