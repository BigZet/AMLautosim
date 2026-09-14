from copy import deepcopy

import pytest
from pydantic import ValidationError

from tests.profile_history_support import profile_config
from tests.purchase_support import mixed_goal
from src.aml_workshop_simulator.schemas.expanded_contract import ExpandedBehavior
from src.aml_workshop_simulator.schemas.round_config import parse_game_config
from src.aml_workshop_simulator.services.profile_history import history_summary
from src.aml_workshop_simulator.services.expanded_simulation import (
    evaluate_expanded_scenario,
    score_expanded_scenario,
)


def parse_input(config):
    value = deepcopy(config)
    value.pop("card_snapshots", None)
    return parse_game_config(value)


def summary(config):
    return history_summary(
        ExpandedBehavior.model_validate(config["behavior"])
    ).model_dump(mode="json")


def test_summary_exact_money_relations_and_category():
    config = profile_config()
    before = deepcopy(config)
    parsed = parse_input(config)
    assert parse_game_config(parsed.dump()).dump() == parsed.dump()
    result = summary(config)
    assert result["activity"] == {
        "count": 5,
        "inflow": "105000.50",
        "outflow": "18500.25",
    }
    assert result["active_days"] == 5 and result["unique_counterparties"] == 3
    assert result["by_operation"]["purchase"]["outflow"] == "3500.25"
    assert result["events"][3]["category"] == "groceries"
    parties = {p["counterparty_id"]: p for p in result["counterparties"]}
    assert parties["A"]["activity"]["count"] == 2
    assert parties["A"]["observation"] == "observed"
    assert (
        parties["B"]["observation"] == "absent"
    )  # Personally known != seen transferring.
    assert config == before
    config["behavior"]["history"]["operations"].reverse()
    assert summary(config) == result


@pytest.mark.parametrize(
    "date",
    [
        "2026-08-14T08:59:59+03:00",
        "2026-09-13T09:00:00+03:00",
        "2026-09-14T09:00:00+03:00",
        "2026-09-01T09:00:00",
    ],
)
def test_reject_dates_outside_half_open_window(date):
    config = profile_config()
    config["behavior"]["history"]["operations"][0]["occurred_at"] = date
    with pytest.raises(ValidationError):
        parse_input(config)


def test_boundary_offsets_and_local_active_days():
    config = profile_config()
    events = config["behavior"]["history"]["operations"]
    events[0]["occurred_at"] = "2026-08-14T06:00:00Z"
    events[-1]["occurred_at"] = "2026-09-13T05:59:59.999999Z"
    assert summary(config)["events"][0]["occurred_at"] == "2026-08-14T09:00:00+03:00"
    assert (
        summary(config)["events"][-1]["occurred_at"]
        == "2026-09-13T08:59:59.999999+03:00"
    )


@pytest.mark.parametrize(
    "index,field,value",
    [
        (1, "id", "h1"),
        (0, "counterparty_id", "missing"),
        (0, "counterparty_id", "A"),
        (3, "counterparty_id", "A"),
        (4, "counterparty_id", "A"),
        (1, "counterparty_id", None),
        (1, "category", "groceries"),
        (3, "category", "wrong"),
        (1, "amount", "NaN"),
        (1, "amount", "0"),
        (1, "amount", "1.001"),
        (1, "hidden_intent", "crime"),
    ],
)
def test_reject_invalid_history(index, field, value):
    config = profile_config()
    config["behavior"]["history"]["operations"][index][field] = value
    with pytest.raises(ValidationError):
        parse_input(config)


def test_unknown_is_not_zero_and_legacy_remains_readable():
    config = profile_config()
    config["behavior"]["history"]["operations"] = None
    unknown = summary(config)
    assert unknown["activity"] is None and unknown["events"] is None
    assert unknown["by_operation"] is None and unknown["active_days"] is None
    assert all(
        p["observation"] == "unknown" and p["activity"] is None
        for p in unknown["counterparties"]
    )
    config["behavior"]["history"]["operations"] = []
    empty = summary(config)
    assert empty["activity"]["count"] == 0 and empty["events"] == []
    assert all(p["observation"] == "absent" for p in empty["counterparties"])
    del config["behavior"]["history"]["version"]
    model = ExpandedBehavior.model_validate(config["behavior"])
    assert history_summary(model) is None
    assert "version" not in model.model_dump(mode="json")["history"]


def test_no_aggregate_input_or_hidden_profile_fields():
    for path, key in [("history", "activity"), ("profile", "risk_score")]:
        config = profile_config()
        config["behavior"][path][key] = 0
        with pytest.raises(ValidationError):
            parse_input(config)


def test_history_does_not_fund_chain_or_change_risk_or_resources():
    config = profile_config()
    steps = mixed_goal(config)
    resource = evaluate_expanded_scenario(steps, config)
    score = score_expanded_scenario(steps, config)
    for events in (None, []):
        changed = deepcopy(config)
        changed["behavior"]["history"]["operations"] = events
        assert evaluate_expanded_scenario(steps, changed) == resource
        assert score_expanded_scenario(steps, changed) == score
    assert resource["totals"]["target_outflow"] == "400000.00"
