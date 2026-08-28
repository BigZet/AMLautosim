from __future__ import annotations

from typing import Any
from decimal import Decimal

from src.aml_workshop_simulator.core.enums import RiskLabel
from src.aml_workshop_simulator.services.action_parameters import action_detail_effects
from src.aml_workshop_simulator.services.catboost_features import extract_catboost_features


COUNTRY_RISK_POINTS = {"low": 0, "medium": 10, "high": 24}
RECIPIENT_POINTS = {
    "known_counterparty": 0,
    "new_counterparty": 12,
    "anonymous_wallet": 25}
TIME_OF_DAY_POINTS = {"day": 0, "evening": 3, "night": 9}
VELOCITY_POINTS = {"spaced": -4, "normal": 0, "rapid": 12}
CHANNEL_POINTS = {
    "bank": -2,
    "branch": -3,
    "mobile": 0,
    "web": 2,
    "atm": 3,
    "exchange": 6}


def _get_card_code(step: dict[str, Any]) -> str:
    card = step.get("card")
    if isinstance(card, dict):
        return card.get("code") or ""
    return step.get("card_code") or ""


def score_steps(steps: list[dict[str, Any]], card_weights: dict[str, float]
                | None = None) -> tuple[float, RiskLabel, dict[str, Any]]:
    """
    Score the sequence of scenario steps.
    Calculates both heuristic AML risk points and extracts the CatBoost feature vector.
    """
    weights = card_weights or {}
    factors: list[dict[str, Any]] = []
    total = 0.0

    for index, step in enumerate(steps, start=1):
        card_code = _get_card_code(step)

        amount = float(step.get("amount", 0))
        frequency = int(step.get("frequency", 1))
        gross = amount * frequency

        ctx = step.get("context", {})
        if not ctx:
            ctx = {
                "country_risk": step.get(
                    "country_risk", "low"), "recipient_type": step.get(
                    "recipient_type", "known_counterparty"), "time_of_day": step.get(
                    "time_of_day", "day"), "velocity": step.get(
                    "velocity", "normal"), "channel": step.get(
                        "channel", "bank"), "has_documents": step.get(
                            "has_documents", True), }

        country_risk = ctx.get("country_risk", "low")
        recipient_type = ctx.get("recipient_type", "known_counterparty")
        time_of_day = ctx.get("time_of_day", "day")
        velocity = ctx.get("velocity", "normal")
        channel = ctx.get("channel", "bank")
        has_documents = bool(ctx.get("has_documents", True))

        details = step.get("action_details") or step.get("details")
        detail_effects = action_detail_effects(card_code, details)

        step_factors = [
            _factor(
                index,
                f"card:{card_code}",
                float(weights.get(card_code, 0)),
                "Базовый риск выбранного типа операции",
            ),
            _factor(
                index,
                "amount",
                min(amount / 20_000, 20),
                "Крупные суммы повышают приоритет проверки",
            ),
            _factor(
                index,
                "frequency",
                max(0, frequency - 1) * 3,
                "Повторы могут быть похожи на дробление операции",
            ),
            _factor(
                index,
                f"country_risk:{country_risk}",
                COUNTRY_RISK_POINTS.get(country_risk, 0),
                "Юрисдикция учитывается как учебный сигнал риска",
            ),
            _factor(
                index,
                f"recipient:{recipient_type}",
                RECIPIENT_POINTS.get(recipient_type, 0),
                "Неизвестный или анонимный получатель повышает неопределенность",
            ),
            _factor(
                index,
                f"time_of_day:{time_of_day}",
                TIME_OF_DAY_POINTS.get(time_of_day, 0),
                "Нетипичное время операции может потребовать проверки",
            ),
            _factor(
                index,
                f"velocity:{velocity}",
                VELOCITY_POINTS.get(velocity, 0),
                "Темп повторов влияет на сходство с автоматизированной цепочкой",
            ),
            _factor(
                index,
                f"channel:{channel}",
                CHANNEL_POINTS.get(channel, 0),
                "Канал операции влияет на доступность подтверждающего контекста",
            ),
            _factor(
                index,
                "documents",
                _document_points(gross, has_documents),
                "Документы снижают неопределенность крупной операции",
            ),
        ]
        step_factors.extend(
            _factor(
                index,
                "detail:"
                f"{card_code}:{factor['field_key']}:{factor['value']}",
                factor["risk_points"],
                factor["description"],
            )
            for factor in detail_effects["factors"]
        )
        factors.extend(step_factors)
        total += sum(factor["points"] for factor in step_factors)

    sequence_factors = _sequence_factors(steps)
    factors.extend(sequence_factors)
    total += sum(factor["points"] for factor in sequence_factors)

    normalized = min(100.0, max(0.0, total / max(1, len(steps))))
    if normalized >= 65:
        label = RiskLabel.suspicious
    elif normalized >= 35:
        label = RiskLabel.review
    else:
        label = RiskLabel.normal

    risk_factors = sorted(
        (factor for factor in factors if factor["points"] >= 0),
        key=lambda item: item["points"],
        reverse=True,
    )
    protective_factors = sorted(
        (factor for factor in factors if factor["points"] < 0),
        key=lambda item: item["points"],
    )

    # Extract CatBoost tabular feature representation
    catboost_features = extract_catboost_features(steps)

    explanation = {
        "schema_version": 2,
        "top_risk_factors": risk_factors[:3],
        "protective_factors": protective_factors[:3],
        "sequence_factors": sequence_factors,
        "all_factors": factors,
        "positive_points": round(sum(max(0.0, factor["points"]) for factor in factors), 2),
        "protective_points": round(sum(min(0.0, factor["points"]) for factor in factors), 2),
        "disclaimer": "Учебная модель; результат не является AML-решением",
        "catboost_features_payload": catboost_features,
    }
    return round(normalized, 2), label, explanation


def _document_points(gross: float, has_documents: bool) -> float:
    if has_documents:
        return -4.0 if gross >= 75_000 else -1.0
    return 7.0 if gross >= 75_000 else 0.0


def _sequence_factors(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    factors: list[dict[str, Any]] = []
    amounts: dict[float, int] = {}
    for step in steps:
        amount = round(float(step.get("amount", 0)), 2)
        if amount >= 10_000:
            amounts[amount] = amounts.get(amount, 0) + 1
    repeated_amounts = sum(1 for count in amounts.values() if count > 1)
    if repeated_amounts:
        factors.append(
            _factor(
                0,
                "sequence:repeated_amounts",
                min(16, repeated_amounts * 8),
                "Одинаковые суммы в разных шагах похожи на шаблонную цепочку",
            )
        )

    credit_codes = {"salary", "cash_deposit", "refund", "salary_transfer"}
    debit_codes = {
        "card_transfer",
        "international",
        "cash_withdrawal",
        "crypto_exchange",
        "online_purchase",
        "split_transfer",
        "cash_out",
        "cross_border",
    }
    for index in range(1, len(steps)):
        previous = steps[index - 1]
        current = steps[index]
        prev_code = _get_card_code(previous)
        curr_code = _get_card_code(current)
        previous_gross = float(previous.get("amount", 0)) * \
            int(previous.get("frequency", 1))
        current_gross = float(current.get("amount", 0)) * \
            int(current.get("frequency", 1))
        if (
            prev_code in credit_codes
            and curr_code in debit_codes
            and previous_gross > 0
            and current_gross >= previous_gross * 0.7
        ):
            factors.append(
                _factor(
                    index + 1,
                    "sequence:rapid_turnover",
                    10,
                    "Большая часть поступления быстро уходит следующим действием",
                ))

    for index, step in enumerate(steps):
        code = _get_card_code(step)
        if code != "cash_deposit":
            continue
        following = steps[index + 1: index + 3]
        for f_step in following:
            f_code = _get_card_code(f_step)
            if f_code in {"crypto_exchange", "international"}:
                factors.append(
                    _factor(
                        index + 2,
                        "sequence:cash_to_high_risk",
                        12,
                        "Наличные вскоре переводятся в высокорисковый канал",
                    )
                )
                break
    return factors


def _factor(step: int, name: str, points: float,
            description: str) -> dict[str, Any]:
    return {
        "step": step,
        "name": name,
        "points": round(float(points), 2),
        "description": description,
    }
