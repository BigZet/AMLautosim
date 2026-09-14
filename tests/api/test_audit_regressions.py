"""Validation and UI regressions found during the pre-release interactive audit."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from src.aml_workshop_simulator.schemas.expanded_contract import Counterparty


def test_party_name_is_trimmed_and_cannot_be_blank():
    party = dict(
        id="test",
        name="  Контрагент  ",
        kind="person",
        information_status="unknown",
        personal_relationship="unknown",
    )
    assert Counterparty.model_validate(party).name == "Контрагент"
    for name in ["", " ", "\t\n"]:
        with pytest.raises(ValidationError):
            Counterparty.model_validate({**party, "name": name})


def test_invalid_history_has_only_relevant_errors_and_keeps_snapshot(
    request_api, admin, round_id
):
    before = request_api("GET", "/admin/rounds/current", admin)
    config = request_api("GET", "/admin/game-config/default", admin)
    config = deepcopy(config)
    config["behavior"]["history"]["operations"][0]["occurred_at"] = config["behavior"][
        "timeline"
    ]["starts_at"]
    result = request_api(
        "PUT",
        f"/admin/rounds/{round_id}",
        admin,
        {"expected_config_revision": before["config_revision"], "game_config": config},
        status=422,
    )
    violations = result["details"]["violations"]
    assert len(violations) == 1
    assert violations[0]["field"] == "game_config.behavior"
    assert "30" in violations[0]["message"]
    assert "GameConfig" not in str(violations)
    assert request_api("GET", "/admin/rounds/current", admin) == before


def test_preview_does_not_publish_legacy_risk_factors(
    request_api, player, active_round
):
    from uuid import uuid4

    card = next(
        c
        for c in request_api("GET", f"/rounds/{active_round}/cards")
        if c["code"] == "salary"
    )
    step = {
        "step_id": str(uuid4()),
        "card": {k: card[k] for k in ("id", "code", "version")},
        "amount": "20000.00",
        "sender_id": "employer",
        "action_details": {"income_basis": "payroll_registry"},
    }
    preview = request_api(
        "POST",
        f"/rounds/{active_round}/scenario/preview",
        player["headers"],
        {"steps": [step]},
    )
    factors = preview["resources"]["per_step"][0]["detail_factors"]
    assert factors and factors[0]["value"] == "payroll_registry"
    assert "risk_points" not in str(preview) and "explanation" not in preview
    assert "description" not in factors[0]
    assert preview["resources"]["resources_after"]["energy"] == 22
    assert preview["resources"]["resources_after"]["time"] == 21
