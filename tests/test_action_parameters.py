from backend.app.domain.action_parameters import (
    action_detail_effects,
    action_fields_for,
    default_action_details,
)
from backend.app.services.scoring import score_steps
from streamlit_apps.demo_admin_data import (
    build_demo_players,
    clear_demo_override,
    demo_board,
    update_demo_block,
    update_demo_override,
)
from streamlit_apps.local_store import ACTION_CARDS, resource_snapshot


def configured_step(card_code: str, details: dict) -> dict:
    card = next(card for card in ACTION_CARDS if card["code"] == card_code)
    return {
        "card_code": card_code,
        "amount": min(50_000, card["max_amount"]),
        "frequency": 1,
        "channel": card["channels"][0],
        "country_risk": "low",
        "recipient_type": "known_counterparty",
        "time_of_day": "day",
        "velocity": "normal",
        "has_documents": True,
        "details": details,
    }


def test_each_action_exposes_its_own_parameter_schema() -> None:
    schemas = {
        card["code"]: {field["key"] for field in action_fields_for(card["code"])}
        for card in ACTION_CARDS
    }

    assert all(schemas.values())
    assert schemas["cash_deposit"] == {"funds_source", "deposit_pattern"}
    assert schemas["crypto_exchange"] == {
        "platform_profile",
        "wallet_owner",
        "asset_profile",
    }
    assert schemas["refund"] == {"refund_reason", "refund_destination"}
    assert schemas["cash_deposit"] != schemas["card_transfer"]


def test_action_details_change_resources_and_model_explanation() -> None:
    safe_details = default_action_details("cash_deposit")
    risky_details = {
        "funds_source": "unexplained",
        "deposit_pattern": "third_party",
    }
    safe_step = configured_step("cash_deposit", safe_details)
    risky_step = configured_step("cash_deposit", risky_details)

    safe_resources = resource_snapshot([safe_step])
    risky_resources = resource_snapshot([risky_step])
    weights = {card["code"]: card["weight"] for card in ACTION_CARDS}
    safe_score, _, _ = score_steps([safe_step], weights)
    risky_score, _, explanation = score_steps([risky_step], weights)

    assert risky_resources["trust"] < safe_resources["trust"]
    assert risky_resources["energy"] < safe_resources["energy"]
    assert risky_score > safe_score
    assert any(
        factor["name"].startswith("detail:cash_deposit:funds_source")
        for factor in explanation["all_factors"]
    )
    assert action_detail_effects("cash_deposit", risky_details)["risk_points"] > 0


def test_demo_admin_can_block_player_and_override_leaderboard() -> None:
    players = build_demo_players()
    player = next(player for player in players if player["id"] == "p-101")
    original = next(
        row for row in demo_board(players) if row["participant_id"] == player["id"]
    )

    update_demo_block(players, player["id"], True, "Проверка профиля")
    update_demo_override(
        players,
        player["id"],
        game_score=42.0,
        risk_score=55.0,
        resource_score=61.0,
        reason="Решение комиссии",
    )
    changed = next(
        row for row in demo_board(players) if row["participant_id"] == player["id"]
    )

    assert player["is_blocked"] is True
    assert changed["is_blocked"] is True
    assert changed["is_overridden"] is True
    assert changed["game_score"] == 42.0
    assert changed["risk_score"] == 55.0

    clear_demo_override(players, player["id"])
    restored = next(
        row for row in demo_board(players) if row["participant_id"] == player["id"]
    )
    assert restored["game_score"] == original["game_score"]
    assert restored["is_overridden"] is False
