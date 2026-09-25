"""Every declared parameter is editable, even with an old visibility list."""

import json
from uuid import uuid4

import pytest


@pytest.mark.parametrize(
    "code",
    ["salary", "incoming_transfer", "card_transfer", "cash_withdrawal", "purchase"],
)
def test_all_parameters_are_exposed_and_saved(
    code, request_api, player, active_round, command, sql
):
    config = sql("SELECT game_config FROM rounds WHERE id=:id", {"id": active_round})[
        0
    ]["game_config"]
    for operation in config["operations"]:
        operation["visible_params"] = []
    sql(
        "UPDATE rounds SET game_config=CAST(:config AS jsonb) WHERE id=:id",
        {"id": active_round, "config": json.dumps(config)},
    )
    path = f"/rounds/{active_round}"
    card = next(c for c in request_api("GET", path + "/cards", player["headers"]) if c["code"] == code)
    expected = (
        ({"channel"} if card["channels"] else set())
        | {f"context.{f['key']}" for f in card["context_fields"]}
        | {f"action.{f['key']}" for f in card["fields"]}
    )
    assert {p["param"] for p in card["visible_params"]} == expected
    assert card["pinned_defaults"] == {}
    step = {
        "step_id": str(uuid4()),
        "card": {k: card[k] for k in ("id", "code", "version")},
        "amount": card["min_amount"],
        "context": {},
        "action_details": {},
    }
    if code in ("salary", "incoming_transfer"):
        step["sender_id"] = "employer" if code == "salary" else "A"
    if code in ("card_transfer", "purchase"):
        step["recipient_id"] = "shop" if code == "purchase" else "A"
    for param in card["visible_params"]:
        value = (
            not param["default"]
            if param["kind"] == "toggle"
            else param["options"][-1]["value"]
        )
        target = (
            step["action_details"]
            if param["namespace"] == "action"
            else step["context"]
        )
        target[param["key"]] = value
    saved = request_api("PUT", path + "/scenario", player["headers"], command([step]))
    reloaded = request_api("GET", path + "/scenario", player["headers"])
    assert saved == reloaded
    for namespace in ("context", "action_details"):
        for key, value in step[namespace].items():
            assert reloaded["steps"][0][namespace][key] == value


@pytest.mark.parametrize(
    "code,namespace,key,value",
    [
        ("salary", "context", "channel", "bank"),
        ("salary", "context", "time_of_day", "day"),
        ("salary", "context", "velocity", "normal"),
        ("salary", "action_details", "employer_profile", "verified_employer"),
        ("cash_withdrawal", "action_details", "cash_purpose", "daily_expenses"),
        ("cash_withdrawal", "action_details", "withdrawal_location", "home_region"),
        ("cash_withdrawal", "context", "recipient_type", "known_counterparty"),
        ("card_transfer", "action_details", "transfer_purpose", "family_support"),
        ("card_transfer", "action_details", "recipient_relationship", "family"),
        ("incoming_transfer", "context", "recipient_type", "known_counterparty"),
        *[
            (code, "context", "has_documents", True)
            for code in (
                "salary",
                "incoming_transfer",
                "card_transfer",
                "cash_withdrawal",
            )
        ],
    ],
)
def test_removed_parameters_are_rejected_without_saving(
    code, namespace, key, value, request_api, player, active_round, command
):
    card = next(
        c
        for c in request_api("GET", f"/rounds/{active_round}/cards", player["headers"])
        if c["code"] == code
    )
    step = {
        "step_id": str(uuid4()),
        "card": {k: card[k] for k in ("id", "code", "version")},
        "amount": card["min_amount"],
        "context": {},
        "action_details": {f["key"]: f["default"] for f in card["fields"]},
    }
    if code in ("salary", "incoming_transfer"):
        step["sender_id"] = "employer" if code == "salary" else "A"
    if code == "card_transfer":
        step["recipient_id"] = "A"
    path = f"/rounds/{active_round}/scenario"
    # Establish a valid control before changing exactly one forbidden field.
    request_api("POST", path + "/preview", player["headers"], {"steps": [step]})
    step[namespace][key] = value
    for suffix, body in [
        ("/preview", {"steps": [step]}),
        ("", command([step])),
        ("/submit", command([step])),
    ]:
        error = request_api(
            "PUT" if not suffix else "POST",
            path + suffix,
            player["headers"],
            body,
            status=422,
        )
        assert error["details"]  # field-specific or whole-step schema rejection
    assert request_api("GET", path, player["headers"]) is None


def test_null_salary_channel_is_canonicalized_as_absent(
    request_api, player, active_round, command
):
    card = next(
        c
        for c in request_api("GET", f"/rounds/{active_round}/cards", player["headers"])
        if c["code"] == "salary"
    )
    step = {
        "step_id": str(uuid4()),
        "card": {k: card[k] for k in ("id", "code", "version")},
        "amount": card["min_amount"],
        "sender_id": "employer",
        "context": {"channel": None},
        "action_details": {},
    }
    path = f"/rounds/{active_round}/scenario"
    saved = request_api("PUT", path, player["headers"], command([step]))
    assert not saved["steps"][0]["context"].get("channel")
    assert request_api("GET", path, player["headers"]) == saved
