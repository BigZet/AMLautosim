from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.aml_dataset.semantic import review_cases, require_review, digest
from src.aml_workshop_simulator.core.errors import Conflict
from src.aml_workshop_simulator.domain.contract_versions import (
    require_new_round_allowed,
)
from src.aml_workshop_simulator.services.semantic_contract import (
    canonical_steps,
    evaluate,
    resource_config,
    resource_steps,
    BehaviorV9,
)
from src.aml_workshop_simulator.services.aml_dataset_features_v4 import extract_features
from src.aml_workshop_simulator.services.expanded_simulation import (
    evaluate_expanded_scenario,
)
from src.aml_workshop_simulator.services.configuration import snapshot_specs
from src.aml_workshop_simulator.services.projections import card_out


@pytest.fixture(scope="module")
def review():
    return review_cases()


@pytest.mark.parametrize(
    "kind", ["bank_transfer", "payment_service", "exchange_withdrawal", "crypto_p2p"]
)
@pytest.mark.parametrize(
    "party", ["A", "B", "C", "D", "employer", "exchange", "shop", "missing"]
)
def test_incoming_role_matrix(review, kind, party):
    config = review[1][0]["config"]
    steps = deepcopy(review[1][0]["steps"])
    incoming = next(s for s in steps if s["card"]["code"] == "incoming_transfer")
    incoming["sender_id"] = party
    incoming["action_details"] = {"incoming_kind": kind}
    if kind == "bank_transfer":
        incoming["action_details"]["bank_country"] = "RU"
    allowed = (
        party == "exchange"
        if kind == "exchange_withdrawal"
        else party in {"A", "B", "C", "D"}
    )
    if allowed:
        canonical_steps(steps, config)
    else:
        with pytest.raises(ValueError):
            canonical_steps(steps, config)


def test_costs_roundtrip_and_strict_details(review):
    for row in review[1]:
        steps, config = row["steps"], row["config"]
        saved = canonical_steps(steps, config)
        assert canonical_steps(json.loads(json.dumps(saved)), config) == saved
        current = evaluate(steps, config)
        previous = evaluate_expanded_scenario(resource_steps(steps, config), resource_config(config))
        for result in (current, previous):
            for step_result in result["per_step"]:
                step_result.pop("detail_factors")
        assert current == previous
    config, steps = review[1][0]["config"], deepcopy(review[1][0]["steps"])
    steps[0]["action_details"] = {"incoming_kind": "crypto_p2p", "bank_country": "RU"}
    with pytest.raises(ValueError):
        canonical_steps(steps, config)


def test_concentration_is_within_transfers(review):
    row = review[1][0]
    f = extract_features(row["steps"], row["config"])
    assert f["recipient_hhi"] == 1
    steps = deepcopy(row["steps"])
    for s in steps:
        if s["card"]["code"] == "cash_withdrawal":
            s["amount"] = "20000"
    assert extract_features(steps, row["config"])["recipient_hhi"] == 1
    assert extract_features(steps, row["config"])["cash_share"] != f["cash_share"]


def test_history_unknown_is_preserved_and_inapplicable_rejected(review):
    config = deepcopy(review[1][0]["config"])
    event = next(
        e
        for e in config["behavior"]["history"]["operations"]
        if e["operation_code"] == "salary"
    )
    event["income_basis"] = None
    assert (
        extract_features(review[1][0]["steps"], config)[
            "history_income_basis_unknown_count"
        ]
        == 1
    )
    event["incoming_kind"] = "crypto_p2p"
    with pytest.raises(ValueError):
        BehaviorV9.model_validate(config["behavior"])


def test_metadata_has_no_legacy_source_or_salary_options(review):
    config = review[1][0]["config"]
    cards = {
        s.code: card_out(s, schema_version=9) for s in snapshot_specs(config).values()
    }
    incoming = {f.key for f in cards["incoming_transfer"].fields}
    assert incoming == {"incoming_kind", "bank_country"}
    assert [o.value for o in cards["salary"].fields[0].options] == ["payroll_registry"]


def test_mass_generation_and_new_rounds_are_gated(review):
    rules, rows = review
    with pytest.raises(ValueError):
        require_review({}, rules, rows)
    with pytest.raises(Conflict):
        require_new_round_allowed(rows[0]["config"])
    require_review(
        dict(status="approved", rubric_sha256=digest(rules), cases_sha256=digest(rows)),
        rules,
        rows,
    )
    changed = deepcopy(rules)
    changed["intensive_activity"]["floor"] = 45
    with pytest.raises(ValueError):
        require_review(
            dict(
                status="approved",
                rubric_sha256=digest(rules),
                cases_sha256=digest(rows),
            ),
            changed,
            rows,
        )


def test_pinned_v8_source_files_unchanged():
    import hashlib

    manifest = json.loads(
        Path("resources/catboost_models/integration-v2-final/manifest.json").read_text()
    )
    root = Path("src/aml_workshop_simulator/services")
    for name, expected in manifest["source_checksums"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
