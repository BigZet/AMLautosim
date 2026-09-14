from copy import deepcopy
from datetime import datetime, UTC

import pytest
from pydantic import ValidationError

from tests.counterparty_support import config_v8, step
from src.aml_workshop_simulator.domain.operation_timeline import operation_timeline
from src.aml_workshop_simulator.schemas.scenarios import ExpandedScenarioStepIn
from src.aml_workshop_simulator.services.counterparties import canonical_expanded_steps
from src.aml_workshop_simulator.services.expanded_simulation import (
    evaluate_expanded_scenario,
    score_expanded_scenario,
)


def chain(config, interval=1):
    values = [step(config), step(config, "card_transfer")]
    values[1]["interval_minutes"] = interval
    return values


@pytest.mark.parametrize(
    "interval,cost,pace",
    [(1, 0, "rapid"), (10, 1, "normal"), (60, 2, "spaced"), (1440, 4, "spaced")],
)
def test_elapsed_minutes_and_exact_resource_charge(interval, cost, pace):
    config = config_v8()
    baseline = evaluate_expanded_scenario(chain(config), config)
    values = chain(config, interval)
    actual = evaluate_expanded_scenario(values, config)
    timing = actual["timeline"]["steps"]
    assert timing[0]["interval_minutes"] is None
    assert timing[0]["waiting_time_cost"] == 0
    assert timing[0]["pace"] is None
    assert timing[1]["elapsed_minutes"] == interval
    assert timing[1]["waiting_time_cost"] == cost
    assert timing[1]["pace"] == pace
    assert (
        actual["resources_after"]["time"] == baseline["resources_after"]["time"] - cost
    )
    assert actual["per_step"][1]["time_cost"] == timing[1]["operation_time_cost"] + cost
    assert timing[1]["operation_time_cost"] == 1  # card base; no old normal/spaced cost
    assert actual["per_step"][0]["time_cost"] == 2  # incoming base 1 + bank-source 1
    poisoned = deepcopy(config)
    for item in poisoned["resource_rules"]["velocity_time"].values():
        item["time_cost"] = 999
    assert evaluate_expanded_scenario(values, poisoned) == actual


def test_first_default_reorder_delete_and_empty():
    config = config_v8()
    values = chain(config, 1440)
    values[0]["interval_minutes"] = 60
    canonical = canonical_expanded_steps(values, config)
    assert [s["interval_minutes"] for s in canonical] == [None, 1440]
    reordered = canonical_expanded_steps(list(reversed(canonical)), config)
    assert [s["interval_minutes"] for s in reordered] == [None, 1]
    assert (
        evaluate_expanded_scenario(reordered, config)["timeline"]["steps"][1][
            "elapsed_minutes"
        ]
        == 1
    )
    assert (
        canonical_expanded_steps(canonical[1:], config)[0]["interval_minutes"] is None
    )
    assert evaluate_expanded_scenario([], config)["timeline"]["steps"] == []
    assert evaluate_expanded_scenario([], config)["resources_after"]["time"] == 30


@pytest.mark.parametrize(
    "start,interval,expected",
    [
        ("2026-09-13T23:59:00+03:00", 1, "2026-09-14T00:00:00+03:00"),
        ("2026-09-13T23:30:00+03:00", 60, "2026-09-14T00:30:00+03:00"),
        ("2026-09-13T23:30:00+03:00", 1440, "2026-09-14T23:30:00+03:00"),
    ],
)
def test_midnight_and_next_day(start, interval, expected):
    config = config_v8()
    config["behavior"]["timeline"]["starts_at"] = start
    assert (
        evaluate_expanded_scenario(chain(config, interval), config)["timeline"][
            "steps"
        ][1]["occurred_at"]
        == expected
    )


@pytest.mark.parametrize(
    "hour,period",
    [
        (0, "night"),
        (5, "night"),
        (6, "day"),
        (17, "day"),
        (18, "evening"),
        (23, "evening"),
    ],
)
def test_time_of_day_boundaries(hour, period):
    config = config_v8()
    config["behavior"]["timeline"]["starts_at"] = f"2026-09-13T{hour:02}:00:00+03:00"
    assert (
        operation_timeline([step(config)], config["behavior"]["timeline"])[0][
            "time_of_day"
        ]
        == period
    )


@pytest.mark.parametrize(
    "start,expected",
    [
        ("2026-03-29T01:30:00+01:00", "2026-03-29T03:30:00+02:00"),
        ("2026-10-25T02:30:00+02:00", "2026-10-25T02:30:00+01:00"),
    ],
)
def test_dst_uses_elapsed_time(start, expected):
    config = config_v8()
    config["behavior"]["timeline"].update(starts_at=start, timezone="Europe/Berlin")
    rows = operation_timeline(chain(config, 60), config["behavior"]["timeline"])
    assert rows[1]["occurred_at"] == expected
    assert (
        datetime.fromisoformat(rows[1]["occurred_at"]).astimezone(UTC)
        - datetime.fromisoformat(start).astimezone(UTC)
    ).total_seconds() == 3600


@pytest.mark.parametrize("bad", [0, 2, True, False, 1.0, "10", -1, 1441])
def test_bad_interval_rejected(bad):
    config = config_v8()
    value = step(config)
    value["interval_minutes"] = bad
    with pytest.raises(ValidationError):
        ExpandedScenarioStepIn.model_validate(value)


@pytest.mark.parametrize(
    "changes",
    [
        {"occurred_at": "2026-01-01"},
        {"elapsed_minutes": 0},
        {"waiting_time_cost": 0},
        {"pace": "spaced"},
        {"context": {"time_of_day": "day"}},
        {"context": {"velocity": "spaced"}},
    ],
)
def test_derived_time_cannot_be_spoofed(changes):
    value = step(config_v8())
    value.update(changes)
    with pytest.raises(ValidationError):
        ExpandedScenarioStepIn.model_validate(value)


def test_insufficient_time_and_channel_cost_preserved():
    config = config_v8()
    values = chain(config, 1440)
    # Override initial time only in the isolated snapshot.
    config["resources"]["initial_time"] = 6
    result = evaluate_expanded_scenario(values, config)
    assert result["resources_after"]["time"] == -1
    assert any(v["reason"] == "insufficient_time" for v in result["violations"])
    values[1]["context"] = {"channel": "branch"}
    branch = evaluate_expanded_scenario(values, config)
    assert branch["resources_after"]["time"] == -3


def test_scorer_uses_only_derived_pace_and_rapid_turnover():
    config = config_v8()
    values = chain(config)
    first = score_expanded_scenario(values, config)
    factors = first["explanation"]["all_factors"]
    assert not any(
        f["code"].startswith("velocity:") and f["step_id"] == values[0]["step_id"]
        for f in factors
    )
    assert any(f["code"] == "sequence:rapid_turnover" for f in factors)
    values[1]["interval_minutes"] = 1440
    slow = score_expanded_scenario(values, config)
    assert not any(
        f["code"] == "sequence:rapid_turnover"
        for f in slow["explanation"]["all_factors"]
    )
    assert slow["explanation"]["scoring_version"] == "expanded-scoring-stage03-v1"
    assert "recipient_type" not in str(slow)
    # Same snapshot and steps give identical calculations without wall-clock reads.
    assert score_expanded_scenario(values, deepcopy(config)) == slow
