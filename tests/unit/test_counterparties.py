import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from tests.counterparty_support import config_v8, copy_step, step
from src.aml_workshop_simulator.core.errors import ValidationFailed
from src.aml_workshop_simulator.schemas.expanded_contract import ExpandedBehavior
from src.aml_workshop_simulator.schemas.scenarios import ScenarioPutIn
from src.aml_workshop_simulator.services.counterparties import (
    canonical_expanded_steps,
    resolve_counterparty_links,
)
from src.aml_workshop_simulator.services.scenario_service import (
    canonical_steps,
    payload_hash,
)


def test_links_are_directional_ordered_and_history_is_separate():
    config = config_v8()
    values = [
        step(config),
        step(config, "card_transfer"),
        step(config, "card_transfer", "B"),
        step(config),
    ]
    original = deepcopy(config)
    links = resolve_counterparty_links(values, config)
    assert links[0]["sender"]["historical_incoming_count"] == 1
    assert links[0]["sender"]["prior_incoming_count"] == 0
    assert links[1]["recipient"]["return_to_observed_sender"]
    assert links[1]["recipient"]["prior_incoming_count"] == 1
    assert links[2]["recipient"]["personal_relationship"] == "known"
    assert links[2]["recipient"]["historical_incoming_count"] == 0
    assert not links[2]["recipient"]["return_to_observed_sender"]
    assert links[3]["sender"]["prior_incoming_count"] == 1
    assert links[3]["sender"]["prior_outgoing_count"] == 1
    assert config == original
    config["behavior"]["history"]["operations"] = []
    swapped = resolve_counterparty_links([values[1], values[0]], config)
    assert not swapped[0]["recipient"]["return_to_observed_sender"]


@pytest.mark.parametrize("history", [None, []])
def test_unknown_history_does_not_invent_activity(history):
    config = config_v8()
    config["behavior"]["history"]["operations"] = history
    party = resolve_counterparty_links([step(config)], config)[0]["sender"]
    assert party["history_available"] == (history is not None)
    assert party["historical_incoming_count"] == (None if history is None else 0)


@pytest.mark.parametrize(
    "code,identity",
    [
        ("incoming_transfer", "A"),
        ("incoming_transfer", "C"),
        ("incoming_transfer", "employer"),
        ("card_transfer", "A"),
        ("card_transfer", "employer"),
        ("salary", "employer"),
        ("cash_withdrawal", None),
    ],
)
def test_roles_roundtrip_without_manual_properties(code, identity):
    config = config_v8()
    original = step(config, code, identity)
    result = canonical_expanded_steps([original], config)
    assert canonical_expanded_steps(json.loads(json.dumps(result)), config) == result
    assert payload_hash(result) == payload_hash(
        canonical_expanded_steps(result, config)
    )
    assert "information_status" not in json.dumps(result)
    assert "sender_relationship" not in json.dumps(result)


@pytest.mark.parametrize(
    "change",
    [
        {"sender_id": None},
        {"sender_id": "foreign-round-id"},
        {"sender_id": "shop"},
        {"recipient_id": "A"},
        {"information_status": "sufficient"},
        {"context": {"recipient_type": "known_counterparty"}},
        {"action_details": {"sender_relationship": "regular_sender"}},
        {"action_details": {"information_status": "sufficient"}},
        {"action_details": {"transfer_source": "invented"}},
        {"context": {"channel": "atm"}},
        {"amount": "0.01"},
    ],
)
def test_bad_references_and_spoofing_rejected(change):
    config = config_v8()
    with pytest.raises(ValidationFailed):
        canonical_expanded_steps([copy_step(step(config), **change)], config)


@pytest.mark.parametrize("code,identity", [("salary", "A"), ("card_transfer", "shop")])
def test_incompatible_party_type(code, identity):
    config = config_v8()
    with pytest.raises(ValidationFailed):
        canonical_expanded_steps([step(config, code, identity)], config)


def test_duplicate_and_foreign_card_rejected():
    config = config_v8()
    value = step(config)
    with pytest.raises(ValidationFailed):
        canonical_expanded_steps([value, value], config)
    value["card"]["id"] += 999
    with pytest.raises(ValidationFailed):
        canonical_expanded_steps([value], config)


def test_catalog_duplicate_ids_and_unknown_history_refs_rejected():
    behavior = config_v8()["behavior"]
    behavior["counterparties"].append(deepcopy(behavior["counterparties"][0]))
    with pytest.raises(ValidationError):
        ExpandedBehavior.model_validate(behavior)
    behavior["counterparties"].pop()
    behavior["history"]["operations"][0]["counterparty_id"] = "another-round"
    with pytest.raises(ValidationError):
        ExpandedBehavior.model_validate(behavior)


def test_transport_accepts_new_ids_but_legacy_normalizer_never_discards_them():
    config = config_v8()
    value = step(config)
    payload = ScenarioPutIn.model_validate(
        dict(steps=[value], expected_revision=0, client_mutation_id=value["step_id"])
    )
    assert payload.steps[0].sender_id == "A"
    with pytest.raises(ValidationFailed, match="v8"):
        canonical_steps(payload.steps)
