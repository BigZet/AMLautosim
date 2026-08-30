"""Behavioral checks: file settings must reach calculations and the editor."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from aml_workshop_simulator.core.game_config import CONFIG_DIR, base_game_config
from aml_workshop_simulator.domain.rules import evaluate_scenario
from aml_workshop_simulator.domain.scoring import score_scenario
from aml_workshop_simulator.schemas.round_config import GameConfigIn
from aml_workshop_simulator.services.catboost_features import (
    extract_catboost_features,
)
from tests.unit.conftest import make_step

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src"


def subprocess_env(**overrides: str) -> dict[str, str]:
    """Environment for a child interpreter, with the package importable.

    A child does not inherit the parent's `sys.path`, and in a src layout the
    package sits one directory below the checkout root.
    """
    existing = os.environ.get("PYTHONPATH")
    path = str(PACKAGE_ROOT) if not existing else f"{PACKAGE_ROOT}{os.pathsep}{existing}"
    return {**os.environ, "PYTHONPATH": path, **overrides}


def test_alternate_files_change_real_calculations(tmp_path):
    config_dir = tmp_path / "settings"
    shutil.copytree(CONFIG_DIR, config_dir)

    def edit(name, change):
        path = config_dir / name
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data))

    edit(
        "base_round.json", lambda c: c["resources"].update(initial_balance="999000.00")
    )
    edit(
        "operations.json",
        lambda c: next(x for x in c["cards"] if x["code"] == "card_transfer").update(
            fee_rate="0.023456", energy_cost=7
        ),
    )
    edit("resource_rules.json", lambda c: c["channel_time"].update(mobile=9))
    edit(
        "parameters.json",
        lambda c: c["action_fields"]["card_transfer"][0]["options"][0].update(
            energy_cost=3
        ),
    )
    edit("risk_rules.json", lambda c: c["channel_points"].update(mobile="42"))
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import json
from aml_workshop_simulator.core.game_config import base_game_config
from aml_workshop_simulator.domain.catalog import CARD_CATALOG
from aml_workshop_simulator.domain.rules import card_spec_from_catalog, evaluate_scenario
from aml_workshop_simulator.domain.scoring import score_scenario
from tests.unit.conftest import make_step
spec = card_spec_from_catalog(next(c for c in CARD_CATALOG if c['code']=='card_transfer'),1)
step = make_step(spec, '10000.00', channel='mobile')
config = base_game_config()
snapshot = evaluate_scenario([step], {spec.key:spec}, config)
risk = score_scenario([step], {spec.key:spec}, config)
print(json.dumps({
    'after': snapshot['resources_after'],
    'step': snapshot['per_step'][0],
    'factors': risk['explanation']['all_factors'],
}))
""",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=subprocess_env(AML_GAME_CONFIG_DIR=str(config_dir)),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["step"]["fee"] == "234.56"
    assert payload["after"]["balance"] == "988765.44"
    assert payload["step"]["energy_cost"] == 10
    assert payload["step"]["time_cost"] == 10
    assert (
        next(f for f in payload["factors"] if f["code"] == "channel:mobile")["points"]
        == "42.00"
    )


def test_missing_configuration_fails_instead_of_using_python_defaults(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from aml_workshop_simulator.core.game_config import base_game_config; base_game_config()",
        ],
        env=subprocess_env(AML_GAME_CONFIG_DIR=str(tmp_path)),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Invalid game configuration" in result.stderr


def test_decimal_weights_are_not_rounded_or_allowed_to_be_negative():
    config = base_game_config()
    config["leaderboard"]["weights"] = {"stealth": "0.333333", "resources": "0.666667"}
    assert (
        GameConfigIn.model_validate(config).dump()["leaderboard"]["weights"]
        == config["leaderboard"]["weights"]
    )
    config["leaderboard"]["weights"] = {"stealth": "-0.2", "resources": "1.2"}
    with pytest.raises(ValidationError):
        GameConfigIn.model_validate(config)


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("risk", "amount_divisor", "0"),
        ("risk", "amount_max_points", "NaN"),
        ("risk", "extra_repeat_points", "-1"),
        ("resource", "minimum_time_cost", -1),
        ("resource", "channel_time", {"branch": 2}),
    ],
)
def test_invalid_coefficients_rejected(section, key, value):
    config = base_game_config()
    target = (
        config["scoring"]["rules"] if section == "risk" else config["resource_rules"]
    )
    target[key] = value
    with pytest.raises(ValidationError):
        GameConfigIn.model_validate(config)


def test_round_coefficients_change_costs_and_risk(spec_by_code, specs):
    config = base_game_config()
    operation = next(o for o in config["operations"] if o["code"] == "card_transfer")
    operation.update(fee_rate="0.023456", energy_cost=4, time_cost=3, risk_weight="40")
    config["resource_rules"]["channel_time"]["mobile"] = 6
    config["resource_rules"]["documents"]["time_cost"] = 8
    step = make_step(spec_by_code["card_transfer"], "100000.00", channel="mobile")
    validated = GameConfigIn.model_validate(config).dump()
    impact = evaluate_scenario([step], specs, validated)["per_step"][0]
    assert impact["fee"] == "2345.60"
    assert impact["energy_cost"] == 4
    assert impact["time_cost"] == 17
    risk = score_scenario([step], specs, validated)
    assert (
        next(f for f in risk["explanation"]["all_factors"] if f["category"] == "card")[
            "points"
        ]
        == "40.00"
    )
    features = extract_catboost_features([step], validated)
    assert features["fees_total"] == 2345.6


def test_sequence_coefficients_really_apply(spec_by_code, specs):
    config = base_game_config()
    config["scoring"]["rules"]["sequence"].update(
        turnover_ratio="0.1", turnover_points="37"
    )
    steps = [
        make_step(spec_by_code["salary"], "100000"),
        make_step(spec_by_code["card_transfer"], "10000"),
    ]
    factors = score_scenario(steps, specs, config)["explanation"]["sequence_factors"]
    assert (
        next(f for f in factors if f["code"] == "sequence:rapid_turnover")["points"]
        == "37.00"
    )


EDITOR_APP = """
import streamlit as st
from aml_workshop_simulator.core.game_config import base_game_config
from aml_workshop_simulator.domain.catalog import CARD_CATALOG
from aml_workshop_simulator.domain.rules import card_spec_from_catalog
from aml_workshop_simulator.api.routers.rounds import card_out
from aml_workshop_simulator.ui.admin.config_editor import render_editor
from aml_workshop_simulator.schemas.round_config import GameConfigIn
cards=[card_out(card_spec_from_catalog(e,i)).model_dump() for i,e in enumerate(CARD_CATALOG,1)]
st.session_state['edited'] = render_editor(st.session_state.get('source', base_game_config()), cards)
"""


def test_editor_preserves_fees_hidden_defaults_and_unlimited_quotas():
    from streamlit.testing.v1 import AppTest

    config = base_game_config()
    operation = next(o for o in config["operations"] if o["code"] == "card_transfer")
    operation["fee_rate"] = "0.023456"
    operation["defaults"] = {
        "context.has_documents": False,
        "action.transfer_purpose": "no_purpose",
    }
    config["constraints"]["category_limits"] = {}
    at = AppTest.from_string(EDITOR_APP)
    at.session_state["source"] = config
    at.run(timeout=30)
    assert not at.exception
    edited = GameConfigIn.model_validate(at.session_state["edited"]).dump()
    saved = next(o for o in edited["operations"] if o["code"] == "card_transfer")
    assert saved["fee_rate"] == "0.023456"
    assert saved["defaults"]["context.has_documents"] is False
    assert saved["defaults"]["action.transfer_purpose"] == "no_purpose"
    assert edited["constraints"]["category_limits"] == {}


def test_editor_switching_presets_uses_new_values():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(EDITOR_APP).run(timeout=30)
    assert not at.exception
    changed = base_game_config()
    changed["resources"]["initial_balance"] = "123000.00"
    changed["operations"][0]["energy_cost"] = 9
    at.session_state["source"] = changed
    at.run(timeout=30)
    assert not at.exception
    edited = at.session_state["edited"]
    assert edited["resources"]["initial_balance"] == "123000.00"
    assert edited["operations"][0]["energy_cost"] == 9
