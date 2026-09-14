from copy import deepcopy

import pytest
from pydantic import ValidationError

from scripts.check_expanded_balance import demo_config, demo_steps
from src.aml_workshop_simulator.core.errors import Conflict
from src.aml_workshop_simulator.domain.contract_versions import (
    require_legacy_contract,
    require_playable_contract,
)
from src.aml_workshop_simulator.domain.simulation import submit_blockers
from src.aml_workshop_simulator.schemas.round_config import parse_game_config
from src.aml_workshop_simulator.services.expanded_simulation import (
    evaluate_expanded_scenario,
)


def test_release_requires_history_and_purchases_and_never_uses_legacy_engine():
    config = demo_config()
    require_playable_contract(config)
    with pytest.raises(Conflict):
        require_legacy_contract(config)
    config.pop("card_snapshots")
    parse_game_config(config)
    for key in ("history", "purchases"):
        invalid = deepcopy(config)
        if key == "history":
            invalid["behavior"][key].pop("version")
        else:
            invalid["behavior"][key] = None
        with pytest.raises(ValidationError):
            parse_game_config(invalid)


@pytest.mark.parametrize(
    "variant,remaining", [("baseline", 10), ("purchase", 9), ("varied", 2)]
)
def test_demonstration_resources(variant, remaining):
    config = demo_config()
    resources = evaluate_expanded_scenario(demo_steps(config, variant), config)
    assert not submit_blockers(resources)
    assert resources["totals"]["target_outflow"] == "400000.00"
    assert resources["resources_after"]["time"] == remaining
    assert config["resources"] == {
        "initial_balance": "180000.00",
        "initial_energy": 30,
        "initial_time": 30,
    }
