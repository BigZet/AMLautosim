from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

from action_parameters import (
    default_action_details,
    default_context,
    normalize_action_details,
)
from scoring import score_steps
from local_store import (
    ACTION_CARDS,
    calculate_game_score,
    resource_snapshot,
)


DEMO_ROUNDS = [
    {
        "id": 1,
        "title": "Мастер-класс AML · демонстрационный раунд",
        "status": "completed",
        "game_config": {
            "initial_balance": 250_000,
            "initial_energy": 14,
            "initial_time": 18,
            "initial_trust": 100,
            "max_actions": 8,
            "target_outflow": 150_000,
            "scoring_version": "rules-v1.1",
        },
    }
]


def _step(
    card_code: str,
    amount: int,
    *,
    frequency: int = 1,
    channel: str | None = None,
    context: dict | None = None,
    details: dict | None = None,
) -> dict:
    card = next(card for card in ACTION_CARDS if card["code"] == card_code)
    values = {
        "country_risk": "low",
        "recipient_type": "known_counterparty",
        "time_of_day": "day",
        "velocity": "normal",
        "has_documents": True,
    }
    values.update(default_context(card_code))
    values.update(context or {})
    selected_details = default_action_details(card_code)
    selected_details.update(details or {})
    return {
        "card_code": card_code,
        "amount": amount,
        "frequency": frequency,
        "channel": channel or card["channels"][0],
        **values,
        "details": normalize_action_details(card_code, selected_details),
    }


def _score(steps: list[dict]) -> dict:
    resources = resource_snapshot(steps)
    if not resources["valid"] or not resources["goal_reached"]:
        raise ValueError(f"Некорректный демо-сценарий: {resources['violations']}")
    weights = {card["code"]: card["weight"] for card in ACTION_CARDS}
    risk_score, label, explanation = score_steps(steps, weights)
    return {
        "risk_score": risk_score,
        "label": label.value,
        "explanation": explanation,
        "resources": resources,
        **calculate_game_score(risk_score, resources),
    }


def _scenario(
    scenario_id: str,
    steps: list[dict],
    submitted_at: str,
    attempts: int,
) -> dict:
    return {
        "id": scenario_id,
        "status": "scored",
        "submitted_at": submitted_at,
        "attempts": attempts,
        "steps": steps,
        "result": _score(steps),
    }


def build_demo_players() -> list[dict]:
    scenarios = {
        "p-101": _scenario(
            "scn-101",
            [
                _step(
                    "online_purchase",
                    100_000,
                    context={"velocity": "spaced"},
                    details={
                        "merchant_profile": "known_marketplace",
                        "delivery_match": "registered_address",
                    },
                ),
                _step(
                    "card_transfer",
                    50_000,
                    context={"velocity": "spaced"},
                    details={
                        "transfer_purpose": "family_support",
                        "recipient_relationship": "own_account",
                    },
                ),
            ],
            "2026-07-16T11:17:42+03:00",
            2,
        ),
        "p-102": _scenario(
            "scn-102",
            [
                _step(
                    "cash_deposit",
                    70_000,
                    channel="atm",
                    details={
                        "funds_source": "asset_sale",
                        "deposit_pattern": "single_location",
                    },
                ),
                _step(
                    "card_transfer",
                    100_000,
                    context={
                        "recipient_type": "new_counterparty",
                        "time_of_day": "evening",
                        "has_documents": False,
                    },
                    details={
                        "transfer_purpose": "goods_payment",
                        "recipient_relationship": "acquaintance",
                    },
                ),
                _step(
                    "online_purchase",
                    50_000,
                    context={"time_of_day": "evening"},
                    details={
                        "merchant_profile": "new_store",
                        "delivery_match": "new_address",
                    },
                ),
            ],
            "2026-07-16T11:19:08+03:00",
            4,
        ),
        "p-103": _scenario(
            "scn-103",
            [
                _step("salary", 100_000),
                _step(
                    "cash_withdrawal",
                    100_000,
                    context={"time_of_day": "night", "velocity": "rapid"},
                    details={
                        "cash_purpose": "unspecified",
                        "withdrawal_location": "other_region",
                    },
                ),
                _step(
                    "crypto_exchange",
                    50_000,
                    context={
                        "country_risk": "high",
                        "time_of_day": "night",
                        "velocity": "rapid",
                        "has_documents": False,
                    },
                    details={
                        "platform_profile": "licensed_exchange",
                        "wallet_owner": "own_wallet",
                        "asset_profile": "privacy_asset",
                    },
                ),
            ],
            "2026-07-16T11:22:33+03:00",
            6,
        ),
        "p-104": _scenario(
            "scn-104",
            [
                _step("card_transfer", 50_000),
                _step(
                    "international",
                    100_000,
                    context={
                        "country_risk": "high",
                        "recipient_type": "new_counterparty",
                        "time_of_day": "evening",
                    },
                    details={
                        "transfer_purpose": "investment",
                        "payment_route": "fintech_gateway",
                    },
                ),
            ],
            "2026-07-16T11:23:51+03:00",
            3,
        ),
        "p-105": _scenario(
            "scn-105",
            [
                _step(
                    "online_purchase",
                    75_000,
                    frequency=2,
                    context={"velocity": "spaced"},
                    details={
                        "merchant_profile": "verified_store",
                        "delivery_match": "pickup_point",
                    },
                )
            ],
            "2026-07-16T11:25:12+03:00",
            1,
        ),
        "p-106": _scenario(
            "scn-106",
            [
                _step(
                    "crypto_exchange",
                    100_000,
                    context={
                        "country_risk": "medium",
                        "time_of_day": "night",
                        "has_documents": False,
                    },
                    details={
                        "platform_profile": "unknown_service",
                        "wallet_owner": "third_party_wallet",
                        "asset_profile": "stablecoin",
                    },
                ),
                _step(
                    "online_purchase",
                    50_000,
                    context={"country_risk": "medium", "time_of_day": "evening"},
                    details={
                        "merchant_profile": "digital_goods",
                        "delivery_match": "no_delivery",
                    },
                ),
            ],
            "2026-07-16T11:26:40+03:00",
            5,
        ),
        "p-107": _scenario(
            "scn-107",
            [
                _step("cash_deposit", 50_000),
                _step("cash_withdrawal", 50_000),
                _step("online_purchase", 100_000),
            ],
            "2026-07-16T11:27:28+03:00",
            2,
        ),
    }
    profiles = [
        ("p-101", "Финансовый детектив", "detective@example.test", "Лицей 1535", "Команда 4"),
        ("p-102", "Аналитик 7", "analyst7@example.test", "Школа 179", "Север"),
        ("p-103", "Команда Альфа", "alpha@example.test", "Школа 57", "Альфа"),
        ("p-104", "Вектор риска", "vector@example.test", "Лицей ВШЭ", "Вектор"),
        ("p-105", "Точный расчет", "calc@example.test", "Гимназия 1514", "Расчет"),
        ("p-106", "Крипто-след", "crypto@example.test", "Школа 548", "След"),
        ("p-107", "Маршрут 12", "route12@example.test", "Школа 1329", "Маршрут"),
        ("p-108", "Новый участник", "newcomer@example.test", "Лицей 1580", "Орбита"),
    ]
    players = []
    for index, (player_id, name, email, organization, team) in enumerate(profiles):
        registered_minute = 42 + index
        player = {
            "id": player_id,
            "name": name,
            "email": email,
            "organization": organization,
            "team": team,
            "registered_at": f"2026-07-16T10:{registered_minute:02d}:00+03:00",
            "last_seen_at": f"2026-07-16T11:{27 - index:02d}:00+03:00",
            "login_count": 1 + (index % 4),
            "is_blocked": player_id == "p-106",
            "blocked_reason": "Проверка учетной записи" if player_id == "p-106" else "",
            "blocked_at": "2026-07-16T11:28:10+03:00" if player_id == "p-106" else None,
            "scenario": scenarios.get(player_id),
            "leaderboard_override": None,
            "activity": [
                {
                    "time": f"10:{registered_minute:02d}",
                    "event": "Регистрация",
                    "source": "participant-ui",
                },
                {
                    "time": f"11:{max(0, 27 - index):02d}",
                    "event": "Последняя активность",
                    "source": "participant-ui",
                },
            ],
        }
        if player["scenario"]:
            player["activity"].append(
                {
                    "time": player["scenario"]["submitted_at"][11:16],
                    "event": "Сценарий отправлен и оценен",
                    "source": "scoring",
                }
            )
        players.append(player)
    return players


def demo_stats(players: list[dict]) -> dict:
    return {
        "registered_users": len(players),
        "submitted_scenarios": sum(player.get("scenario") is not None for player in players),
        "scored_scenarios": sum(
            bool(player.get("scenario", {}).get("result"))
            for player in players
            if player.get("scenario")
        ),
        "blocked_users": sum(player.get("is_blocked", False) for player in players),
    }


def demo_board(players: list[dict]) -> list[dict]:
    board = []
    for player in players:
        scenario = player.get("scenario")
        result = scenario.get("result") if scenario else None
        if result is None:
            continue
        override = player.get("leaderboard_override") or {}
        risk_score = float(override.get("risk_score", result["risk_score"]))
        label = "suspicious" if risk_score >= 65 else "review" if risk_score >= 35 else "normal"
        board.append(
            {
                "participant_id": player["id"],
                "participant_name": player["name"],
                "email": player["email"],
                "scenario_id": scenario["id"],
                "risk_score": risk_score,
                "game_score": float(override.get("game_score", result["game_score"])),
                "resource_score": float(
                    override.get("resource_score", result["resource_score"])
                ),
                "label": label,
                "top_factors": result["explanation"]["top_factors"],
                "is_blocked": player["is_blocked"],
                "is_overridden": bool(override),
                "override_reason": override.get("reason", ""),
            }
        )
    board.sort(key=lambda row: (-row["game_score"], row["risk_score"]))
    return board


def update_demo_block(
    players: list[dict],
    player_id: str,
    blocked: bool,
    reason: str = "",
) -> None:
    player = next(player for player in players if player["id"] == player_id)
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    player["is_blocked"] = blocked
    player["blocked_reason"] = reason.strip() if blocked else ""
    player["blocked_at"] = timestamp if blocked else None
    player["activity"].append(
        {
            "time": timestamp[11:16],
            "event": "Доступ заблокирован" if blocked else "Доступ восстановлен",
            "source": "admin-ui",
        }
    )


def update_demo_override(
    players: list[dict],
    player_id: str,
    *,
    game_score: float,
    risk_score: float,
    resource_score: float,
    reason: str,
) -> None:
    player = next(player for player in players if player["id"] == player_id)
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    player["leaderboard_override"] = {
        "game_score": round(float(game_score), 1),
        "risk_score": round(float(risk_score), 1),
        "resource_score": round(float(resource_score), 1),
        "reason": reason.strip(),
        "updated_at": timestamp,
    }
    player["activity"].append(
        {
            "time": timestamp[11:16],
            "event": "Результат лидерборда скорректирован",
            "source": "admin-ui",
        }
    )


def clear_demo_override(players: list[dict], player_id: str) -> None:
    player = next(player for player in players if player["id"] == player_id)
    player["leaderboard_override"] = None
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    player["activity"].append(
        {
            "time": timestamp[11:16],
            "event": "Восстановлен расчет модели",
            "source": "admin-ui",
        }
    )


def clone_rounds() -> list[dict]:
    return deepcopy(DEMO_ROUNDS)
