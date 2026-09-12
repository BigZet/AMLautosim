"""Exact reduced contracts, sparse storage and compensated game balance."""

from decimal import Decimal
from uuid import uuid4

import pytest

from scripts.check_game_balance import ROUTE_OPTIONS, ROUTES, play
from src.aml_workshop_simulator.core.game_config import base_game_config
from src.aml_workshop_simulator.domain.catalog import CARD_CATALOG
from src.aml_workshop_simulator.domain.game_models import (
    card_spec_from_catalog,
)
from src.aml_workshop_simulator.domain.round_policy import RoundPolicy, declared_params
from src.aml_workshop_simulator.domain.scoring import score_scenario
from src.aml_workshop_simulator.domain.simulation import evaluate_scenario
from src.aml_workshop_simulator.schemas.scenarios import ScenarioStepIn, StoredStep
from src.aml_workshop_simulator.services.catboost_features import (
    extract_catboost_features,
)
from src.aml_workshop_simulator.services.scenario_service import canonical_steps

EXPECTED = {
    "salary": ["action.income_basis"],
    "cash_withdrawal": ["channel", "context.time_of_day", "context.velocity"],
    "card_transfer": [
        "channel",
        "context.time_of_day",
        "context.recipient_type",
        "context.velocity",
    ],
    "incoming_transfer": [
        "channel",
        "context.velocity",
        "action.sender_relationship",
        "action.transfer_source",
        "context.time_of_day",
    ],
}
SPECS = {
    s.key: s
    for i, c in enumerate(CARD_CATALOG, 1)
    if (s := card_spec_from_catalog(c, i))
}
CONFIG = base_game_config()
POLICY = RoundPolicy.from_config(CONFIG, SPECS)


def build(code, amount="20000"):
    spec = SPECS[(code, 1)]
    step = ScenarioStepIn.model_validate(
        {
            "step_id": str(uuid4()),
            "card": {"id": spec.id, "code": code, "version": 1},
            "amount": amount,
            "action_details": {f["key"]: f["default"] for f in spec.fields},
        }
    )
    return canonical_steps([step], SPECS, POLICY)[0]


@pytest.mark.parametrize("code", EXPECTED)
def test_exact_contract_and_sparse_stored_context(code):
    spec = SPECS[(code, 1)]
    assert list(declared_params(spec)) == EXPECTED[code]
    step = build(code)
    serialized = StoredStep.model_validate(step).model_dump(mode="json")
    expected_context = {
        p.split(".")[-1] for p in EXPECTED[code] if not p.startswith("action.")
    }
    assert set(step["context"]) == set(serialized["context"]) == expected_context
    assert set(step["action_details"]) == {
        p[7:] for p in EXPECTED[code] if p.startswith("action.")
    }


@pytest.mark.parametrize("code", EXPECTED)
def test_every_retained_option_can_be_evaluated(code):
    spec = SPECS[(code, 1)]
    for param in declared_params(spec):
        field = spec.field_spec(param)
        for option in field["options"]:
            step = build(code)
            target = "action_details" if param.startswith("action.") else "context"
            step[target][param.split(".")[-1]] = option["value"]
            evaluate_scenario([step], SPECS, CONFIG)
            score_scenario([step], SPECS, CONFIG)


@pytest.mark.parametrize(
    "code", ["incoming_transfer", "card_transfer", "cash_withdrawal"]
)
def test_amount_boundary_replaces_documents_exactly(code):
    samples = []
    for amount in ["59999.99", "60000.00", "60000.01"]:
        step = build(code, amount)
        snapshot = evaluate_scenario([step], SPECS, CONFIG)
        risk = score_scenario([step], SPECS, CONFIG)
        factors = risk["explanation"]["all_factors"]
        assert not any("documents" in f["code"] for f in factors)
        adjustments = [f for f in factors if f["code"] == "amount:adjustment"]
        assert len(adjustments) == int(Decimal(amount) >= 60000)
        if adjustments:
            assert adjustments[0]["points"] == "-5.00"
        samples.append((snapshot["per_step"][0]["time_cost"], risk["risk_score"]))
    assert samples[1][0] == samples[0][0] + 1 and samples[2][0] == samples[1][0]
    assert samples[1][1] == samples[0][1] - 5 and samples[2][1] == samples[1][1]


@pytest.mark.parametrize(
    "name, risk, score, balance, energy, time",
    [
        ("transfers", "20.00", "61.51", "8000.00", 11, 3),
        ("mixed", "25.83", "53.38", "3000.00", 3, 0),
        ("incoming_funding", "21.00", "58.84", "7950.00", 9, 1),
    ],
)
def test_reference_routes_keep_scores_and_resources(
    name, risk, score, balance, energy, time
):
    snapshot, r, b = play(ROUTES[name], **ROUTE_OPTIONS.get(name, {}))
    assert str(r["risk_score"]) == risk and str(b["game_score"]) == score
    after = snapshot["resources_after"]
    assert (after["balance"], after["energy"], after["time"]) == (balance, energy, time)


def test_salary_has_no_context_factors_or_channel_features():
    step = build("salary")
    factors = score_scenario([step], SPECS, CONFIG)["explanation"]["all_factors"]
    assert not any(f["category"] == "context" for f in factors)
    features = extract_catboost_features([step], CONFIG)
    assert features["primary_channel"] == "none"
    assert features["unique_channels_count"] == 0
    assert not any("docs" in key for key in features)
