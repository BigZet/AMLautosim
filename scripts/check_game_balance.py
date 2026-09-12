"""Reproducible baseline playthroughs, without a database: python -m scripts.check_game_balance."""

from itertools import product
from uuid import UUID

from src.aml_workshop_simulator.core.game_config import base_game_config
from src.aml_workshop_simulator.domain.catalog import CARD_CATALOG
from src.aml_workshop_simulator.domain.game_models import card_spec_from_catalog
from src.aml_workshop_simulator.domain.round_policy import RoundPolicy
from src.aml_workshop_simulator.domain.scoring import (
    leaderboard_scores,
    resource_score,
    score_scenario,
)
from src.aml_workshop_simulator.domain.simulation import (
    evaluate_scenario,
    submit_blockers,
)
from src.aml_workshop_simulator.schemas.scenarios import ScenarioStepIn
from src.aml_workshop_simulator.services.scenario_service import canonical_steps

ROUTES = {
    "transfers": [
        ("incoming_transfer", 80000),
        ("card_transfer", 80000),
        ("card_transfer", 80000),
        ("incoming_transfer", 80000),
        ("card_transfer", 80000),
        ("card_transfer", 80000),
        ("incoming_transfer", 70000),
        ("card_transfer", 80000),
    ],
    "mixed": [
        ("salary", 30000),
        ("card_transfer", 80000),
        ("card_transfer", 80000),
        ("incoming_transfer", 70000),
        ("card_transfer", 80000),
        ("incoming_transfer", 70000),
        ("incoming_transfer", 55000),
        ("card_transfer", 80000),
        ("card_transfer", 80000),
    ],
    "incoming_funding": [
        ("incoming_transfer", 80000),
        ("card_transfer", 78000),
        ("card_transfer", 78000),
        ("incoming_transfer", 80000),
        ("card_transfer", 78000),
        ("cash_withdrawal", 10000),
        ("incoming_transfer", 70000),
        ("card_transfer", 78000),
        ("card_transfer", 78000),
    ],
}

# Long route without salary; the resource budget limits usable slots.
LONG_ROUTE = [
    ("incoming_transfer", 80000),
    ("card_transfer", 48750),
    ("card_transfer", 48750),
    ("incoming_transfer", 80000),
    ("card_transfer", 48750),
    ("card_transfer", 48750),
    ("cash_withdrawal", 10000),
    ("card_transfer", 48750),
    ("card_transfer", 48750),
    ("incoming_transfer", 70000),
    ("card_transfer", 48750),
    ("card_transfer", 48750),
]

ROUTE_OPTIONS = {"mixed": {"velocity": "rapid"}}


def play(
    route,
    velocity="normal",
    branch=False,
    transfer_source="domestic_bank",
    sender_relationship="regular_sender",
):
    config = base_game_config()
    specs = {
        s.key: s
        for i, c in enumerate(CARD_CATALOG, 1)
        if (s := card_spec_from_catalog(c, i))
    }
    policy = RoundPolicy.from_config(config, specs)
    inputs = []
    for i, (code, amount) in enumerate(route, 1):
        spec = specs[(code, 1)]
        context = {}
        if code in ("card_transfer", "cash_withdrawal"):
            context["velocity"] = velocity
        if branch and code == "cash_withdrawal":
            context["channel"] = "branch"
        details = {f["key"]: f["default"] for f in spec.fields}
        if code == "incoming_transfer":
            details.update(
                transfer_source=transfer_source, sender_relationship=sender_relationship
            )
        inputs.append(
            ScenarioStepIn.model_validate(
                {
                    "step_id": str(UUID(int=i)),
                    "card": {"id": spec.id, "code": code, "version": 1},
                    "amount": str(amount),
                    "context": context,
                    "action_details": details,
                }
            )
        )
    steps = canonical_steps(inputs, specs, policy)
    snapshot = evaluate_scenario(steps, specs, config)
    risk = score_scenario(steps, specs, config)
    board = leaderboard_scores(
        risk["risk_score"], resource_score(snapshot, config), config
    )
    return snapshot, risk, board


def main():
    for name, route in ROUTES.items():
        snapshot, _, _ = play(route, **ROUTE_OPTIONS.get(name, {}))
        assert not submit_blockers(snapshot), (name, snapshot["violations"])
    assert not submit_blockers(play(LONG_ROUTE, velocity="rapid")[0])
    # The old one-card shortcut and a chain without funding must fail.
    assert submit_blockers(play([("card_transfer", 240000)])[0])
    assert submit_blockers(play([("card_transfer", 80000)] * 3)[0])
    for name, velocity, branch in product(
        ROUTES, ("spaced", "normal", "rapid"), (False, True)
    ):
        snapshot, risk, board = play(ROUTES[name], velocity, branch=branch)
        blockers = submit_blockers(snapshot)
        print(
            f"{name:12} {velocity:6} branch={branch!s:5} "
            f"valid={not blockers!s:5} risk={risk['risk_score']:5} "
            f"label={risk['risk_label'].value:10} score={board['game_score']:5} "
            f"left={snapshot['resources_after']} "
            f"blockers={sorted({b['reason'] for b in blockers})}"
        )


if __name__ == "__main__":
    main()
