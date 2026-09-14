"""Snapshot construction for stage-04 tests and the isolated UI workbench."""

import json
from dataclasses import asdict

from tests.counterparty_support import config_v8, step, FIXTURES
from copy import deepcopy
from src.aml_workshop_simulator.domain.catalog import catalog_entry
from src.aml_workshop_simulator.domain.game_models import card_spec_from_catalog


def purchase_config():
    config = config_v8()
    config["behavior"]["purchases"] = {
        "version": "purchase-policy-v1",
        "max_total": "30000.00",
    }
    spec = card_spec_from_catalog(catalog_entry("purchase"), 5)
    config["card_snapshots"].append(json.loads(json.dumps(asdict(spec), default=str)))
    config["operations"].append(
        {"code": "purchase", "version": 1, "visible_params": []}
    )
    return config


def mixed_goal(config):
    cases = json.loads((FIXTURES / "legacy-v7.json").read_text())["cases"]
    values = deepcopy(
        next(c["steps"] for c in cases if c["name"] == "incoming_funding")
    )
    for item in values:
        code = item["card"]["code"]
        item["context"] = {k: v for k, v in item["context"].items() if k == "channel"}
        item["action_details"].pop("sender_relationship", None)
        item.update(
            sender_id="A"
            if code == "incoming_transfer"
            else "employer"
            if code == "salary"
            else None,
            recipient_id="A" if code == "card_transfer" else None,
            interval_minutes=1,
        )
    values.append(step(config, "purchase", "shop"))
    return values
