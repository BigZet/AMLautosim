from __future__ import annotations

import hashlib
import hmac
import os
import threading
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import streamlit as st

from action_parameters import (
    action_detail_effects,
    normalize_action_details,
)
from scoring import score_steps


INITIAL_BALANCE = 250_000
INITIAL_ENERGY = 14
INITIAL_TIME = 18
INITIAL_TRUST = 100
MAX_ACTIONS = 8
MAX_IDENTICAL_STEPS = 2
MAX_NIGHT_OPERATIONS = 2
TARGET_OUTFLOW = 150_000

ROUND_LIMITS = {
    "cash": {"label": "Наличные операции", "limit": 150_000},
    "international": {"label": "Международные переводы", "limit": 180_000},
    "crypto": {"label": "Криптовалюта", "limit": 100_000},
    "anonymous": {"label": "Анонимные получатели", "limit": 75_000},
    "high_risk_country": {"label": "Страны высокого риска", "limit": 100_000},
}

ACTION_CARDS = [
    {
        "code": "salary",
        "title": "Получить зарплату",
        "category": "Поступление",
        "description": "Регулярное поступление от известного работодателя.",
        "weight": 0,
        "icon": ":material/account_balance_wallet:",
        "flow": "credit",
        "energy_cost": 1,
        "time_cost": 1,
        "trust_cost": 0,
        "fee_rate": 0,
        "min_amount": 10_000,
        "max_amount": 150_000,
        "max_frequency": 2,
        "round_frequency_limit": 2,
        "channels": ["bank", "mobile"],
    },
    {
        "code": "cash_deposit",
        "title": "Внести наличные",
        "category": "Наличные",
        "description": "Пополнение счета через банкомат или кассу.",
        "weight": 12,
        "icon": ":material/payments:",
        "flow": "credit",
        "energy_cost": 2,
        "time_cost": 2,
        "trust_cost": 5,
        "fee_rate": 0,
        "min_amount": 5_000,
        "max_amount": 150_000,
        "max_frequency": 3,
        "round_frequency_limit": 3,
        "channels": ["atm", "branch"],
    },
    {
        "code": "card_transfer",
        "title": "Перевести по карте",
        "category": "Перевод",
        "description": "Перевод другому клиенту банка.",
        "weight": 5,
        "icon": ":material/credit_card:",
        "flow": "debit",
        "energy_cost": 1,
        "time_cost": 1,
        "trust_cost": 1,
        "fee_rate": 0.005,
        "min_amount": 1_000,
        "max_amount": 500_000,
        "max_frequency": 5,
        "round_frequency_limit": 7,
        "channels": ["mobile", "web", "branch"],
    },
    {
        "code": "international",
        "title": "Международный перевод",
        "category": "Перевод",
        "description": "Отправка средств в другую страну.",
        "weight": 18,
        "icon": ":material/public:",
        "flow": "debit",
        "energy_cost": 3,
        "time_cost": 3,
        "trust_cost": 12,
        "fee_rate": 0.02,
        "min_amount": 5_000,
        "max_amount": 180_000,
        "max_frequency": 3,
        "round_frequency_limit": 3,
        "channels": ["web", "branch"],
    },
    {
        "code": "cash_withdrawal",
        "title": "Снять наличные",
        "category": "Наличные",
        "description": "Получение наличных вскоре после поступления.",
        "weight": 14,
        "icon": ":material/local_atm:",
        "flow": "debit",
        "energy_cost": 2,
        "time_cost": 2,
        "trust_cost": 8,
        "fee_rate": 0.01,
        "min_amount": 5_000,
        "max_amount": 120_000,
        "max_frequency": 4,
        "round_frequency_limit": 4,
        "channels": ["atm", "branch"],
    },
    {
        "code": "crypto_exchange",
        "title": "Купить криптовалюту",
        "category": "Цифровые активы",
        "description": "Перевод средств на криптовалютную площадку.",
        "weight": 20,
        "icon": ":material/currency_bitcoin:",
        "flow": "debit",
        "energy_cost": 3,
        "time_cost": 3,
        "trust_cost": 15,
        "fee_rate": 0.015,
        "min_amount": 5_000,
        "max_amount": 100_000,
        "max_frequency": 3,
        "round_frequency_limit": 3,
        "channels": ["exchange", "web"],
    },
    {
        "code": "online_purchase",
        "title": "Оплатить покупку",
        "category": "Покупка",
        "description": "Оплата товара в интернет-магазине.",
        "weight": 2,
        "icon": ":material/shopping_cart:",
        "flow": "debit",
        "energy_cost": 1,
        "time_cost": 1,
        "trust_cost": 0,
        "fee_rate": 0,
        "min_amount": 1_000,
        "max_amount": 250_000,
        "max_frequency": 5,
        "round_frequency_limit": 6,
        "channels": ["mobile", "web"],
    },
    {
        "code": "refund",
        "title": "Получить возврат",
        "category": "Поступление",
        "description": "Возврат возможен только после покупки в этой цепочке.",
        "weight": 4,
        "icon": ":material/replay:",
        "flow": "credit",
        "energy_cost": 1,
        "time_cost": 1,
        "trust_cost": 2,
        "fee_rate": 0,
        "min_amount": 1_000,
        "max_amount": 150_000,
        "max_frequency": 3,
        "round_frequency_limit": 3,
        "channels": ["mobile", "web"],
        "requires_purchase": True,
    },
]

RECIPIENT_TRUST_COST = {
    "known_counterparty": 0,
    "new_counterparty": 3,
    "anonymous_wallet": 10,
}
COUNTRY_TRUST_COST = {"low": 0, "medium": 4, "high": 10}
TIME_TRUST_COST = {"day": 0, "evening": 2, "night": 7}
VELOCITY_TRUST_COST = {"spaced": 0, "normal": 1, "rapid": 7}
CHANNEL_TRUST_MODIFIER = {
    "bank": -2,
    "branch": -3,
    "mobile": 0,
    "web": 2,
    "atm": 2,
    "exchange": 4,
}


def resource_snapshot(steps: list[dict]) -> dict:
    """Calculate resources, contextual trade-offs and hard-rule violations."""
    card_lookup = {card["code"]: card for card in ACTION_CARDS}
    balance = float(INITIAL_BALANCE)
    energy = INITIAL_ENERGY
    time_left = INITIAL_TIME
    trust = INITIAL_TRUST
    outflow = 0.0
    fees = 0.0
    refundable = 0.0
    night_operations = 0
    previous_code: str | None = None
    identical_streak = 0
    card_frequencies: dict[str, int] = {}
    limit_usage = {code: 0.0 for code in ROUND_LIMITS}
    limit_reported: set[str] = set()
    violations: list[str] = []
    impacts: list[dict] = []

    if len(steps) > MAX_ACTIONS:
        violations.append(f"В сценарии может быть не больше {MAX_ACTIONS} действий.")

    for index, step in enumerate(steps, start=1):
        card_code = step.get("card_code")
        card = card_lookup.get(card_code)
        if card is None:
            violations.append(f"Шаг {index}: неизвестный тип операции.")
            continue

        amount = float(step.get("amount", 0))
        frequency = int(step.get("frequency", 1))
        country_risk = step.get("country_risk", "low")
        recipient_type = step.get("recipient_type", "known_counterparty")
        time_of_day = step.get("time_of_day", "day")
        velocity = step.get("velocity", "normal")
        has_documents = bool(step.get("has_documents", True))
        channel = step.get("channel", card["channels"][0])
        details = normalize_action_details(card_code, step.get("details"))
        detail_effects = action_detail_effects(card_code, details)
        gross = amount * frequency
        fee = gross * card["fee_rate"]
        energy_cost = card["energy_cost"] * frequency + detail_effects["energy_cost"]

        velocity_time = {"spaced": frequency, "normal": 0, "rapid": -max(0, frequency - 1)}.get(
            velocity, 0
        )
        document_time = 1 if has_documents and gross >= 75_000 else 0
        channel_time = 2 if channel == "branch" else 0
        time_cost = max(
            1,
            card["time_cost"] * frequency
            + velocity_time
            + document_time
            + channel_time
            + detail_effects["time_cost"],
        )

        contextual_trust = (
            RECIPIENT_TRUST_COST.get(recipient_type, 0)
            + COUNTRY_TRUST_COST.get(country_risk, 0)
            + TIME_TRUST_COST.get(time_of_day, 0)
            + VELOCITY_TRUST_COST.get(velocity, 0)
            + CHANNEL_TRUST_MODIFIER.get(channel, 0)
        )
        if not has_documents and gross >= 75_000:
            contextual_trust += 8
        trust_cost = max(
            0,
            card["trust_cost"] * frequency
            + contextual_trust
            + detail_effects["trust_cost"],
        )

        if amount < card["min_amount"] or amount > card["max_amount"]:
            violations.append(
                f"Шаг {index}: сумма должна быть от {card['min_amount']:,.0f} до "
                f"{card['max_amount']:,.0f} ₽."
            )
        if frequency < 1 or frequency > card["max_frequency"]:
            violations.append(
                f"Шаг {index}: для этой операции доступно не больше "
                f"{card['max_frequency']} повторов."
            )
        if channel not in card["channels"]:
            violations.append(f"Шаг {index}: выбран недоступный канал операции.")

        card_frequencies[card_code] = card_frequencies.get(card_code, 0) + frequency
        if card_frequencies[card_code] > card["round_frequency_limit"]:
            violations.append(
                f"Шаг {index}: общий лимит операции «{card['title']}» — "
                f"{card['round_frequency_limit']} повторов за раунд."
            )

        if previous_code == card_code:
            identical_streak += 1
        else:
            identical_streak = 1
            previous_code = card_code
        if identical_streak > MAX_IDENTICAL_STEPS:
            violations.append(
                f"Шаг {index}: нельзя ставить больше {MAX_IDENTICAL_STEPS} одинаковых "
                "операций подряд."
            )

        if time_of_day == "night":
            night_operations += 1
            if night_operations > MAX_NIGHT_OPERATIONS:
                violations.append(
                    f"Шаг {index}: ночью доступно не больше {MAX_NIGHT_OPERATIONS} операций."
                )

        if card.get("requires_purchase") and gross > refundable:
            violations.append(f"Шаг {index}: возврат превышает сумму предыдущих покупок.")

        if card["flow"] == "credit":
            money_delta = gross - fee
            if card.get("requires_purchase"):
                refundable = max(0.0, refundable - gross)
        else:
            money_delta = -(gross + fee)
            outflow += gross
            if card_code == "online_purchase":
                refundable += gross

        if card_code in {"cash_deposit", "cash_withdrawal"}:
            limit_usage["cash"] += gross
        if card_code == "international":
            limit_usage["international"] += gross
        if card_code == "crypto_exchange":
            limit_usage["crypto"] += gross
        if recipient_type == "anonymous_wallet":
            limit_usage["anonymous"] += gross
        if country_risk == "high":
            limit_usage["high_risk_country"] += gross

        for limit_code, config in ROUND_LIMITS.items():
            if limit_usage[limit_code] > config["limit"] and limit_code not in limit_reported:
                violations.append(
                    f"Шаг {index}: превышен лимит «{config['label']}» "
                    f"({config['limit']:,.0f} ₽ за раунд)."
                )
                limit_reported.add(limit_code)

        balance += money_delta
        energy -= energy_cost
        time_left -= time_cost
        trust -= trust_cost
        fees += fee
        if balance < 0:
            violations.append(f"Шаг {index}: недостаточно денег для операции и комиссии.")
        if energy < 0:
            violations.append(f"Шаг {index}: не хватает энергии.")
        if time_left < 0:
            violations.append(f"Шаг {index}: не хватает времени раунда.")
        if trust < 0:
            violations.append(f"Шаг {index}: исчерпан запас доверия.")

        impacts.append(
            {
                "money_delta": round(money_delta, 2),
                "energy_cost": energy_cost,
                "time_cost": time_cost,
                "trust_cost": trust_cost,
                "fee": round(fee, 2),
                "detail_effects": detail_effects,
                "balance_after": round(balance, 2),
                "energy_after": energy,
                "time_after": time_left,
                "trust_after": trust,
            }
        )

    limits = [
        {
            "code": code,
            "label": config["label"],
            "used": round(limit_usage[code], 2),
            "limit": config["limit"],
            "remaining": round(max(0.0, config["limit"] - limit_usage[code]), 2),
        }
        for code, config in ROUND_LIMITS.items()
    ]
    snapshot = {
        "balance": round(balance, 2),
        "energy": energy,
        "time": time_left,
        "trust": trust,
        "slots": max(0, MAX_ACTIONS - len(steps)),
        "outflow": round(outflow, 2),
        "fees": round(fees, 2),
        "goal_reached": outflow >= TARGET_OUTFLOW,
        "valid": not violations,
        "violations": violations,
        "steps": impacts,
        "limits": limits,
    }
    snapshot["resource_score"] = resource_efficiency(snapshot)
    return snapshot


def resource_efficiency(resources: dict) -> float:
    """Return a 0-100 score for resources preserved after reaching the goal."""

    def ratio(value: float, maximum: float) -> float:
        return max(0.0, min(1.0, value / maximum))

    outflow = max(1.0, float(resources.get("outflow", 0)))
    fee_score = 1.0 - min(1.0, float(resources.get("fees", 0)) / outflow)
    score = (
        ratio(float(resources.get("balance", 0)), INITIAL_BALANCE) * 20
        + ratio(float(resources.get("energy", 0)), INITIAL_ENERGY) * 15
        + ratio(float(resources.get("time", 0)), INITIAL_TIME) * 15
        + ratio(float(resources.get("trust", 0)), INITIAL_TRUST) * 25
        + fee_score * 15
        + ratio(float(resources.get("slots", 0)), MAX_ACTIONS) * 10
    )
    return round(score, 1)


def calculate_game_score(risk_score: float, resources: dict) -> dict:
    """Combine model evasion and resource efficiency into the leaderboard score."""
    stealth_score = round(max(0.0, 100.0 - risk_score), 1)
    resource_score = resource_efficiency(resources)
    total = round(stealth_score * 0.6 + resource_score * 0.4, 1)
    return {
        "game_score": total,
        "stealth_score": stealth_score,
        "resource_score": resource_score,
        "weights": {"stealth": 0.6, "resources": 0.4},
    }


def _password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return f"{salt.hex()}:{digest.hex()}"


def _password_matches(password: str, encoded: str) -> bool:
    salt_hex, expected = encoded.split(":", maxsplit=1)
    actual = _password_hash(password, bytes.fromhex(salt_hex)).split(":", maxsplit=1)[1]
    return hmac.compare_digest(actual, expected)


@dataclass
class LocalStore:
    users: dict[str, dict] = field(default_factory=dict)
    scenarios: dict[str, dict] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def register(self, name: str, email: str, password: str) -> dict:
        normalized_email = email.strip().lower()
        if len(name.strip()) < 2:
            raise ValueError("Укажите имя длиной не менее двух символов.")
        if "@" not in normalized_email:
            raise ValueError("Введите корректный email.")
        if len(password) < 4:
            raise ValueError("Пароль должен содержать не менее четырех символов.")
        with self.lock:
            if normalized_email in self.users:
                raise ValueError("Участник с таким email уже зарегистрирован.")
            user = {
                "id": uuid4().hex,
                "name": name.strip(),
                "email": normalized_email,
                "password_hash": _password_hash(password),
            }
            self.users[normalized_email] = user
            return self._public_user(user)

    def login(self, email: str, password: str) -> dict:
        with self.lock:
            user = self.users.get(email.strip().lower())
            if user is None or not _password_matches(password, user["password_hash"]):
                raise ValueError("Неверный email или пароль.")
            return self._public_user(user)

    def submit(self, user_id: str, steps: list[dict]) -> dict:
        if not steps:
            raise ValueError("Добавьте хотя бы одно действие.")
        resources = resource_snapshot(steps)
        if not resources["valid"]:
            raise ValueError(resources["violations"][0])
        if not resources["goal_reached"]:
            raise ValueError(
                f"Проведите минимум {TARGET_OUTFLOW:,.0f} ₽ через расходные операции."
            )
        scenario = {
            "id": uuid4().hex,
            "user_id": user_id,
            "steps": deepcopy(steps),
            "status": "submitted",
            "submitted_at": datetime.now(UTC).isoformat(),
            "result": None,
        }
        with self.lock:
            self.scenarios[user_id] = scenario
        return deepcopy(scenario)

    def get_scenario(self, user_id: str) -> dict | None:
        with self.lock:
            scenario = self.scenarios.get(user_id)
            return deepcopy(scenario) if scenario else None

    def score(self, user_id: str) -> dict:
        with self.lock:
            scenario = self.scenarios.get(user_id)
            if scenario is None:
                raise ValueError("Сначала отправьте сценарий.")
            self._score_locked(scenario)
            return deepcopy(scenario)

    def score_all(self) -> int:
        with self.lock:
            for scenario in self.scenarios.values():
                self._score_locked(scenario)
            return len(self.scenarios)

    def leaderboard(self) -> list[dict]:
        with self.lock:
            user_by_id = {user["id"]: user for user in self.users.values()}
            rows = []
            for scenario in self.scenarios.values():
                result = scenario.get("result")
                user = user_by_id.get(scenario["user_id"])
                if result is None or user is None:
                    continue
                resources = result["resources"]
                rows.append(
                    {
                        "name": user["name"],
                        "user_id": user["id"],
                        "game_score": result["game_score"],
                        "risk_score": result["risk_score"],
                        "stealth_score": result["stealth_score"],
                        "resource_score": result["resource_score"],
                        "balance": resources["balance"],
                        "energy": resources["energy"],
                        "time": resources["time"],
                        "trust": resources["trust"],
                        "fees": resources["fees"],
                        "submitted_at": scenario["submitted_at"],
                    }
                )
            rows.sort(
                key=lambda row: (
                    -row["game_score"],
                    row["risk_score"],
                    -row["resource_score"],
                    row["submitted_at"],
                )
            )
            for rank, row in enumerate(rows, start=1):
                row["rank"] = rank
            return deepcopy(rows)

    def status_counts(self) -> dict:
        with self.lock:
            return {
                "registered": len(self.users),
                "submitted": len(self.scenarios),
                "scored": sum(
                    scenario.get("result") is not None
                    for scenario in self.scenarios.values()
                ),
            }

    @staticmethod
    def _public_user(user: dict) -> dict:
        return {key: user[key] for key in ("id", "name", "email")}

    @staticmethod
    def _score_locked(scenario: dict) -> None:
        weights = {card["code"]: card["weight"] for card in ACTION_CARDS}
        risk_score, label, explanation = score_steps(scenario["steps"], weights)
        resources = resource_snapshot(scenario["steps"])
        rating = calculate_game_score(risk_score, resources)
        scenario["status"] = "scored"
        scenario["result"] = {
            "risk_score": risk_score,
            "label": label.value,
            "explanation": explanation,
            "resources": resources,
            **rating,
        }


@st.cache_resource
def get_store() -> LocalStore:
    """Shared in-memory store for all sessions of this Streamlit process."""
    return LocalStore()
