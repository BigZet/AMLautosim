import pytest

from streamlit_apps.local_store import (
    INITIAL_TIME,
    INITIAL_TRUST,
    LocalStore,
    calculate_game_score,
    resource_snapshot,
)


def step(
    card_code: str,
    amount: int,
    frequency: int = 1,
) -> dict:
    return {
        "card_code": card_code,
        "amount": amount,
        "frequency": frequency,
        "country_risk": "low",
        "recipient_type": "known_counterparty",
    }


def test_resource_snapshot_tracks_money_energy_and_goal() -> None:
    result = resource_snapshot([step("card_transfer", 150_000)])

    assert result["valid"] is True
    assert result["goal_reached"] is True
    assert result["balance"] == 99_250
    assert result["energy"] == 13
    assert result["fees"] == 750


def test_resource_snapshot_blocks_overspending_and_exhaustion() -> None:
    overspending = resource_snapshot([step("card_transfer", 500_000)])
    exhausted = resource_snapshot(
        [step("international", 1_000, frequency=3)] * 2
    )

    assert overspending["valid"] is False
    assert "недостаточно денег" in overspending["violations"][0]
    assert exhausted["valid"] is False
    assert any("не хватает энергии" in item for item in exhausted["violations"])


def test_refund_requires_an_earlier_purchase() -> None:
    invalid = resource_snapshot([step("refund", 20_000)])
    valid = resource_snapshot(
        [step("online_purchase", 20_000), step("refund", 20_000)]
    )

    assert invalid["valid"] is False
    assert "возврат" in invalid["violations"][0]
    assert valid["valid"] is True


def test_store_rejects_scenario_below_round_goal() -> None:
    store = LocalStore()

    with pytest.raises(ValueError, match="Проведите минимум"):
        store.submit("player", [step("online_purchase", 10_000)])


def test_context_consumes_time_trust_and_enforces_anonymous_limit() -> None:
    contextual_step = {
        **step("card_transfer", 80_000),
        "recipient_type": "anonymous_wallet",
        "country_risk": "high",
        "time_of_day": "night",
        "velocity": "rapid",
        "channel": "web",
        "has_documents": False,
    }

    result = resource_snapshot([contextual_step])

    assert result["time"] < INITIAL_TIME
    assert result["trust"] < INITIAL_TRUST
    assert result["valid"] is False
    assert any("Анонимные получатели" in item for item in result["violations"])


def test_resource_rating_rewards_a_more_efficient_route_at_the_same_risk() -> None:
    efficient = resource_snapshot([step("online_purchase", 150_000)])
    expensive = resource_snapshot([step("card_transfer", 150_000)])

    efficient_score = calculate_game_score(25, efficient)
    expensive_score = calculate_game_score(25, expensive)

    assert efficient_score["resource_score"] > expensive_score["resource_score"]
    assert efficient_score["game_score"] > expensive_score["game_score"]


def test_leaderboard_is_sorted_by_composite_game_score() -> None:
    store = LocalStore()
    efficient_user = store.register("Экономный", "efficient@example.com", "pass123")
    expensive_user = store.register("Затратный", "expensive@example.com", "pass123")

    store.submit(efficient_user["id"], [step("online_purchase", 150_000)])
    store.submit(expensive_user["id"], [step("card_transfer", 150_000)])
    store.score_all()

    board = store.leaderboard()

    assert [row["rank"] for row in board] == [1, 2]
    assert board[0]["name"] == "Экономный"
    assert board[0]["game_score"] > board[1]["game_score"]
