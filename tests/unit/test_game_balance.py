"""Behavioral guardrails for the playable default, separate from engine fixtures."""

import pytest

from scripts.check_game_balance import LONG_ROUTE, ROUTE_OPTIONS, ROUTES, play
from src.aml_workshop_simulator.domain.simulation import submit_blockers


@pytest.mark.parametrize("name", ROUTES)
def test_default_has_multiple_reachable_routes(name):
    assert not submit_blockers(play(ROUTES[name], **ROUTE_OPTIONS.get(name, {}))[0])


def test_goal_needs_funding_and_more_than_one_debit():
    assert submit_blockers(play([("card_transfer", 240000)])[0])
    snapshot = play([("card_transfer", 80000)] * 3)[0]
    assert "insufficient_balance" in {v["reason"] for v in snapshot["violations"]}


def test_speed_and_documents_have_resource_risk_tradeoffs():
    route = ROUTES["transfers"]
    regular, regular_risk, _ = play(route)
    fast, fast_risk, _ = play(route, velocity="rapid")
    undocumented, undocumented_risk, _ = play(route, documents=False)
    risky, risky_risk, _ = play(route, velocity="rapid", documents=False)
    for snapshot in (regular, fast, undocumented, risky):
        assert not submit_blockers(snapshot)
    assert fast["resources_after"]["time"] > regular["resources_after"]["time"]
    assert undocumented["resources_after"]["time"] > regular["resources_after"]["time"]
    assert fast_risk["risk_score"] > regular_risk["risk_score"]
    assert undocumented_risk["risk_score"] > regular_risk["risk_score"]
    assert regular_risk["risk_label"].value == "review"
    assert fast_risk["risk_label"].value == "review"
    assert risky_risk["risk_label"].value == "suspicious"
    assert "insufficient_time" in {
        v["reason"] for v in play(route, velocity="spaced")[0]["violations"]
    }


def test_long_route_is_playable_with_tight_resources():
    snapshot, _, _ = play(LONG_ROUTE, velocity="rapid")
    assert not submit_blockers(snapshot)
    assert snapshot["resources_after"]["available_steps"] == 2
    assert snapshot["resources_after"]["energy"] == 3
    ordinary = play(LONG_ROUTE)[0]
    assert not submit_blockers(ordinary)
    assert ordinary["resources_after"]["time"] == 0


def test_salary_requires_sacrificing_resources_elsewhere():
    ordinary = play(ROUTES["mixed"])[0]
    assert "insufficient_time" in {v["reason"] for v in ordinary["violations"]}
    accelerated = play(ROUTES["mixed"], velocity="rapid")[0]
    assert not submit_blockers(accelerated)
    salary = accelerated["per_step"][0]
    assert salary["energy_cost"] == 8
    assert salary["time_cost"] == 9
