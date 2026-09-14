"""Isolated stage-02 fixtures; never install them as a live round default."""

import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

FIXTURES = Path(__file__).parent / "fixtures/contracts"


def config_v8():
    config = json.loads((FIXTURES / "legacy-v7.json").read_text())["config"]
    config["schema_version"] = 8
    config["behavior"] = json.loads(
        (FIXTURES / "expanded-v8-behavior.json").read_text()
    )
    config["behavior"]["counterparties"] = json.loads(
        (FIXTURES / "counterparties-v8.json").read_text()
    )
    return config


def step(config, code="incoming_transfer", identity="A"):
    card = next(c for c in config["card_snapshots"] if c["code"] == code)
    return dict(
        step_id=str(uuid4()),
        card={k: card[k] for k in ("id", "code", "version")},
        amount=card["min_amount"],
        context={},
        action_details={},
        sender_id=identity if code in {"incoming_transfer", "salary"} else None,
        recipient_id=identity if code in {"card_transfer", "purchase"} else None,
        interval_minutes=None,
    )


def copy_step(value, **changes):
    return {**deepcopy(value), **changes}
