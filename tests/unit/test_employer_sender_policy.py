from copy import deepcopy

import pytest
from pydantic import ValidationError

from scripts.check_expanded_balance import demo_config
from tests.counterparty_support import step
from src.aml_workshop_simulator.core.errors import ValidationFailed
from src.aml_workshop_simulator.services.counterparties import canonical_expanded_steps
from src.aml_workshop_simulator.schemas.expanded_contract import ExpandedBehavior
from src.aml_workshop_simulator.ui.nicegui.counterparties import party_options


def test_employer_is_only_salary_sender_in_new_policy():
    config = demo_config()
    assert "employer" not in party_options(config, "incoming_transfer")[1]
    assert set(party_options(config, "salary")[1]) == {"employer"}
    with pytest.raises(ValidationFailed):
        canonical_expanded_steps(
            [step(config, "incoming_transfer", "employer")], config
        )
    assert canonical_expanded_steps([step(config, "salary", "employer")], config)
    assert canonical_expanded_steps([step(config)], config)
    assert canonical_expanded_steps([step(config, "card_transfer", "employer")], config)


def test_category_not_id_defines_employer_and_other_institutions_still_receive():
    config = demo_config()
    party = deepcopy(
        next(p for p in config["behavior"]["counterparties"] if p["id"] == "employer")
    )
    party.update(id="company", category="other")
    config["behavior"]["counterparties"].append(party)
    assert "company" in party_options(config, "incoming_transfer")[1]
    assert "company" not in party_options(config, "salary")[1]
    assert canonical_expanded_steps(
        [step(config, "incoming_transfer", "company")], config
    )
    with pytest.raises(ValidationFailed):
        canonical_expanded_steps([step(config, "salary", "company")], config)


def test_old_snapshot_keeps_previous_semantics_and_shape():
    config = demo_config()
    config["behavior"].pop("sender_policy")
    assert "employer" in party_options(config, "incoming_transfer")[1]
    assert canonical_expanded_steps(
        [step(config, "incoming_transfer", "employer")], config
    )
    assert "sender_policy" not in ExpandedBehavior.model_validate(
        config["behavior"]
    ).model_dump(mode="json")


def test_history_uses_same_sender_policy_and_unknown_policy_is_rejected():
    behavior = demo_config()["behavior"]
    behavior["history"]["operations"][1]["counterparty_id"] = "employer"
    with pytest.raises(ValidationError):
        ExpandedBehavior.model_validate(behavior)
    behavior.pop("sender_policy")
    ExpandedBehavior.model_validate(behavior)
    behavior["sender_policy"] = "unknown-policy"
    with pytest.raises(ValidationError):
        ExpandedBehavior.model_validate(behavior)
