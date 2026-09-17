from copy import deepcopy
import pytest

from src.aml_workshop_simulator.domain.operation_purposes import (
    allowed_purposes,
    default_purpose,
)
from src.aml_workshop_simulator.services.aml_context import canonical_steps
from src.aml_workshop_simulator.services.game_classifier import get_game_classifier
from src.aml_workshop_simulator.ui.nicegui.aml_context import purpose_options


@pytest.mark.parametrize(
    "code,kind,purpose,valid",
    [
        ("salary", None, "salary", True),
        ("salary", None, "loan", False),
        ("salary", None, "unknown", False),
        ("purchase", None, "salary", False),
        ("purchase", None, "personal_spending", True),
        ("cash_withdrawal", None, "salary", False),
        ("cash_withdrawal", None, "personal_spending", True),
        ("incoming_transfer", "crypto_p2p", "salary", False),
        ("incoming_transfer", "crypto_p2p", "asset_sale", True),
        ("incoming_transfer", "exchange_withdrawal", "shared_expense", False),
        ("incoming_transfer", "exchange_withdrawal", "unknown", True),
        ("incoming_transfer", "bank_transfer", "refund", True),
        ("card_transfer", None, "loan", True),
        ("card_transfer", None, "salary", False),
    ],
)
def test_shared_editor_and_server_policy(code, kind, purpose, valid):
    model = get_game_classifier()
    config = model.context
    card = next(c for c in config["card_snapshots"] if c["code"] == code)
    details = (
        {"income_basis": "payroll_registry"}
        if code == "salary"
        else {"incoming_kind": kind}
        if code == "incoming_transfer"
        else {}
    )
    if kind == "bank_transfer":
        details["bank_country"] = "RU"
    step = dict(
        step_id="f33dbb01-64f5-4d8f-b7c6-39bc2d553001",
        card={k: card[k] for k in ("id", "code", "version")},
        amount=card["min_amount"],
        context={},
        action_details=details,
        interval_minutes=None,
        purpose_code=purpose,
        claim_id=None,
    )
    if code in ("salary", "incoming_transfer"):
        step["sender_id"] = (
            "employer"
            if code == "salary"
            else "exchange"
            if kind == "exchange_withdrawal"
            else "A"
        )
    elif code != "cash_withdrawal":
        step["recipient_id"] = "shop" if code == "purchase" else "B"
    assert (purpose in purpose_options(config, step)) is valid
    if valid:
        assert canonical_steps([step], config)[0]["purpose_code"] == purpose
    else:
        with pytest.raises(ValueError, match="Назначение не соответствует"):
            canonical_steps([step], config)
    assert default_purpose(step) in allowed_purposes(step)


def test_valid_purpose_does_not_pretend_to_change_classifier():
    import json
    from pathlib import Path

    steps = json.loads(
        (Path(__file__).parents[1] / "fixtures/game_classifier_chain.json").read_text()
    )
    if isinstance(steps, dict):
        steps = steps["steps"]
    model = get_game_classifier()
    changed = deepcopy(steps)
    next(s for s in changed if s["card"]["code"] == "incoming_transfer")[
        "purpose_code"
    ] = "refund"
    assert model.predict(
        steps, model.context, explain=False, require_pin=False
    ) == model.predict(changed, model.context, explain=False, require_pin=False)
