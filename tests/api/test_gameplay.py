"""The current incoming contract through the complete FastAPI game lifecycle."""

from itertools import product

import pytest


@pytest.mark.parametrize(
    "source,sender",
    list(
        product(
            ["domestic_bank", "foreign_bank_kg", "crypto_exchange", "payment_service"],
            [
                "A",
                "B",
                "C",
            ],
        )
    ),
)
def test_incoming_profiles_complete_game(
    source, sender, request_api, admin, player, active_round, chain, command
):
    path = f"/rounds/{active_round}"
    headers = player["headers"]
    cards = request_api("GET", path + "/cards", player["headers"])
    incoming = next(c for c in cards if c["code"] == "incoming_transfer")
    assert [p["key"] for p in incoming["visible_params"]] == [
        "channel",
        "incoming_kind",
        "bank_country",
    ]
    assert {c["code"] for c in cards} == {
        "salary",
        "incoming_transfer",
        "card_transfer",
        "cash_withdrawal",
        "purchase",
    }
    steps = chain()
    for step in steps:
        if step["card"]["code"] == "incoming_transfer":
            step["action_details"] = {
                "domestic_bank": {"incoming_kind": "bank_transfer", "bank_country": "RU"},
                "foreign_bank_kg": {"incoming_kind": "bank_transfer", "bank_country": "KG"},
                "crypto_exchange": {"incoming_kind": "crypto_p2p"},
                "payment_service": {"incoming_kind": "payment_service"},
            }[source]
            step["purpose_code"] = "unknown"
            step["sender_id"] = sender
    preview = request_api("POST", path + "/scenario/preview", headers, {"steps": steps})
    assert preview["can_submit"]
    assert preview["resources"]["limit_usage"]["cash"] == "10000.00"
    assert preview["resources"]["limit_usage"]["anonymous"] == "0.00"
    saved = request_api("PUT", path + "/scenario", headers, command(steps))
    assert saved["resources"] == preview["resources"]
    assert request_api("GET", path + "/scenario", headers) == saved
    submission = command(saved["steps"], saved["revision"])
    submitted = request_api("POST", path + "/scenario/submit", headers, submission)
    assert submitted["status"] == "submitted"
    assert (
        request_api("POST", path + "/scenario/submit", headers, submission) == submitted
    )
    summary = request_api("POST", f"/admin/rounds/{active_round}/score?wait=true", admin)
    assert summary["scored_count"] == 1
    result = request_api("GET", path + "/result", headers)
    assert result["rank"] == 1
    assert result["resources"] == preview["resources"]
    (row,) = request_api("GET", path + "/leaderboard", headers)["rows"]
    assert row["is_current_user"] and row["rank"] == result["rank"]
    for key in ("game_score", "resource_score", "stealth_score", "risk_label"):
        assert row[key] == result["scores"][key]
    state = request_api("GET", "/rounds/current/state", headers)
    assert state["round"]["status"] == "completed"
    assert state["result"] == result
    assert not state["can_edit"] and state["can_view_leaderboard"]


# Existing result assertions use the explicit transitional wait contract.
pytestmark = pytest.mark.usefixtures("scoring_worker")
