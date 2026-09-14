"""Fixed demonstration routes, never a search for ways to evade bank monitoring."""

import json
from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from src.aml_workshop_simulator.core.expanded_game import expanded_game_config
from src.aml_workshop_simulator.domain.catalog import SEED_CARD_CATALOG
from src.aml_workshop_simulator.domain.game_models import card_spec_from_catalog
from src.aml_workshop_simulator.domain.simulation import submit_blockers
from src.aml_workshop_simulator.services.expanded_simulation import (
    evaluate_expanded_scenario,
)

ROUTE = [
    ("incoming_transfer", 80000),
    ("card_transfer", 78000),
    ("card_transfer", 78000),
    ("incoming_transfer", 80000),
    ("card_transfer", 78000),
    ("cash_withdrawal", 10000),
    ("incoming_transfer", 70000),
    ("card_transfer", 78000),
    ("card_transfer", 78000),
]


def demo_config():
    config = expanded_game_config(datetime.fromisoformat("2026-09-13T09:00:00+03:00"))
    config["card_snapshots"] = [
        json.loads(json.dumps(asdict(card_spec_from_catalog(c, i)), default=str))
        for i, c in enumerate(SEED_CARD_CATALOG, 1)
    ]
    return config


def demo_steps(config, variant="baseline"):
    cards = {c["code"]: c for c in config["card_snapshots"]}
    route = ROUTE + ([("purchase", 1000)] if variant != "baseline" else [])
    values = []
    for index, (code, amount) in enumerate(route):
        card = cards[code]
        party = "B" if variant == "varied" and index % 2 else "A"
        values.append(
            {
                "step_id": str(UUID(int=index + 1)),
                "card": {k: card[k] for k in ("id", "code", "version")},
                "amount": str(amount),
                "context": {},
                "action_details": {"transfer_source": "domestic_bank"}
                if code == "incoming_transfer"
                else {},
                "sender_id": party if code == "incoming_transfer" else None,
                "recipient_id": "shop"
                if code == "purchase"
                else party
                if code == "card_transfer"
                else None,
                "interval_minutes": None
                if index == 0
                else {1: 10, 3: 60, 6: 1440}.get(index, 1)
                if variant == "varied"
                else 1,
            }
        )
    return values


def main():
    config = demo_config()
    for name in ("baseline", "purchase", "varied"):
        snapshot = evaluate_expanded_scenario(demo_steps(config, name), config)
        blockers = submit_blockers(snapshot)
        print(
            json.dumps(
                {
                    "strategy": name,
                    "totals": snapshot["totals"],
                    "resources": snapshot["resources_after"],
                    "blockers": blockers,
                },
                ensure_ascii=False,
            )
        )
        if blockers:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
