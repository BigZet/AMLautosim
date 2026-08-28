from __future__ import annotations

from typing import Any
from decimal import Decimal
from datetime import datetime, timezone

from src.aml_workshop_simulator.services.local_rules import (
    ACTION_CARDS,
    INITIAL_BALANCE,
    INITIAL_ENERGY,
    INITIAL_TIME,
    INITIAL_TRUST,
    MAX_ACTIONS,
    MAX_IDENTICAL_STEPS,
    MAX_NIGHT_OPERATIONS,
    ROUND_LIMITS,
    TARGET_OUTFLOW,
    RECIPIENT_TRUST_COST,
    COUNTRY_TRUST_COST,
    TIME_TRUST_COST,
    VELOCITY_TRUST_COST,
    CHANNEL_TRUST_MODIFIER,
)
from src.aml_workshop_simulator.services.action_parameters import (
    action_detail_effects,
    normalize_action_details,
)


def calculate_resource_snapshot(
        steps: list[dict[str, Any]], round_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Calculates resource usage, contextual costs, limits, and violations
    for a list of scenario steps according to the round configuration.
    """
    cfg_resources = round_config.get("resources", {}) if round_config else {}
    init_balance = float(cfg_resources.get("initial_balance", INITIAL_BALANCE))
    init_energy = int(cfg_resources.get("initial_energy", INITIAL_ENERGY))
    init_time = int(cfg_resources.get("initial_time", INITIAL_TIME))
    init_trust = int(cfg_resources.get("initial_trust", INITIAL_TRUST))

    cfg_obj = round_config.get("objectives", {}) if round_config else {}
    target_outflow = float(cfg_obj.get("target_outflow", TARGET_OUTFLOW))
    max_actions = int(cfg_obj.get("max_actions", MAX_ACTIONS))

    cfg_constraints = round_config.get(
        "constraints", {}) if round_config else {}
    max_identical = int(
        cfg_constraints.get(
            "max_identical_steps",
            MAX_IDENTICAL_STEPS))
    max_night = int(
        cfg_constraints.get(
            "max_night_operations",
            MAX_NIGHT_OPERATIONS))
    cat_limits = cfg_constraints.get("category_limits", {})

    card_lookup = {c["code"]: c for c in ACTION_CARDS}

    balance = init_balance
    energy = init_energy
    time_left = init_time
    trust = init_trust
    outflow = 0.0
    inflow = 0.0
    fees = 0.0
    refundable = 0.0
    night_operations = 0
    previous_code: str | None = None
    identical_streak = 0
    card_frequencies: dict[str, int] = {}

    limit_usage = {code: 0.0 for code in ROUND_LIMITS}
    limit_reported: set[str] = set()
    violations: list[str] = []
    impacts: list[dict[str, Any]] = []

    if len(steps) > max_actions:
        violations.append(
            f"В сценарии может быть не больше {max_actions} действий.")

    for index, step in enumerate(steps, start=1):
        if "card" in step and isinstance(step["card"], dict):
            card_code = step["card"].get("code", "")
        else:
            card_code = step.get("card_code", "")

        card = card_lookup.get(card_code)
        if card is None:
            violations.append(
                f"Шаг {index}: неизвестный тип операции '{card_code}'.")
            continue

        amount = float(step.get("amount", 0.0))
        frequency = int(step.get("frequency", 1))

        ctx = step.get("context", {})
        if not ctx:
            ctx = {
                "country_risk": step.get(
                    "country_risk", "low"), "recipient_type": step.get(
                    "recipient_type", "known_counterparty"), "time_of_day": step.get(
                    "time_of_day", "day"), "velocity": step.get(
                    "velocity", "normal"), "channel": step.get(
                        "channel", card["channels"][0]), "has_documents": step.get(
                            "has_documents", True), }

        country_risk = ctx.get("country_risk", "low")
        recipient_type = ctx.get("recipient_type", "known_counterparty")
        time_of_day = ctx.get("time_of_day", "day")
        velocity = ctx.get("velocity", "normal")
        channel = step.get("channel") or ctx.get("channel") or (card["channels"][0] if card.get("channels") else "branch")
        has_documents = bool(ctx.get("has_documents", True))

        raw_details = step.get("action_details") or step.get("details")
        details = normalize_action_details(card_code, raw_details)
        detail_effects = action_detail_effects(card_code, details)

        gross = amount * frequency
        fee = gross * float(card["fee_rate"])
        energy_cost = card["energy_cost"] * \
            frequency + detail_effects["energy_cost"]

        velocity_time = {"spaced": frequency, "normal": 0,
                         "rapid": -max(0, frequency - 1)}.get(velocity, 0)
        document_time = 1 if has_documents and gross >= 75_000 else 0
        channel_time = 2 if channel in ("branch", "bank") else 0
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

        if amount < float(
                card["min_amount"]) or amount > float(
                card["max_amount"]):
            violations.append(
                f"Шаг {index}: сумма должна быть от {
                    card['min_amount']:,.0f} до " f"{
                    card['max_amount']:,.0f} ₽.")
        if frequency < 1 or frequency > card["max_frequency"]:
            violations.append(
                f"Шаг {index}: для этой операции доступно не больше "
                f"{card['max_frequency']} повторов."
            )
        allowed_channels = set(card.get("channels", []))
        if "branch" in allowed_channels:
            allowed_channels.add("bank")
        if "bank" in allowed_channels:
            allowed_channels.add("branch")
        if channel not in allowed_channels and card.get("channels"):
            violations.append(
                f"Шаг {index}: выбран недоступный канал операции.")

        card_frequencies[card_code] = card_frequencies.get(
            card_code, 0) + frequency
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
        if identical_streak > max_identical:
            violations.append(
                f"Шаг {index}: нельзя ставить больше {max_identical} одинаковых "
                "операций подряд."
            )

        if time_of_day == "night":
            night_operations += 1
            if night_operations > max_night:
                violations.append(
                    f"Шаг {index}: ночью доступно не больше {max_night} операций.")

        if card.get(
                "requires_card_code") == "online_purchase" and gross > refundable:
            violations.append(
                f"Шаг {index}: возврат превышает сумму предыдущих покупок.")

        if card["flow"] == "credit":
            money_delta = gross - fee
            inflow += gross
            if card.get("requires_card_code") == "online_purchase":
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
            limit_val = float(cat_limits.get(limit_code, config["limit"]))
            if limit_usage[limit_code] > limit_val and limit_code not in limit_reported:
                violations.append(
                    f"Шаг {index}: превышен лимит «{config['label']}» "
                    f"({limit_val:,.0f} ₽ за раунд)."
                )
                limit_reported.add(limit_code)

        balance += money_delta
        energy -= energy_cost
        time_left -= time_cost
        trust -= trust_cost
        fees += fee

        if balance < 0:
            violations.append(
                f"Шаг {index}: недостаточно денег для операции и комиссии.")
        if energy < 0:
            violations.append(f"Шаг {index}: не хватает энергии.")
        if time_left < 0:
            violations.append(f"Шаг {index}: не хватает времени раунда.")
        if trust < 0:
            violations.append(f"Шаг {index}: исчерпан запас доверия.")

        impacts.append(
            {
                "step_index": index,
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
            "limit": float(cat_limits.get(code, config["limit"])),
            "remaining": round(max(0.0, float(cat_limits.get(code, config["limit"])) - limit_usage[code]), 2),
        }
        for code, config in ROUND_LIMITS.items()
    ]

    goal_reached = outflow >= target_outflow
    valid = len(violations) == 0

    resource_score = calculate_resource_score(
        balance=balance,
        energy=energy,
        time_left=time_left,
        trust=trust,
        slots=max(0, max_actions - len(steps)),
        outflow=outflow,
        fees=fees,
        init_balance=init_balance,
        init_energy=init_energy,
        init_time=init_time,
        init_trust=init_trust,
        max_actions=max_actions,
    )

    return {
        "schema_version": 2,
        "valid": valid,
        "goal_reached": goal_reached,
        "violations": violations,
        "resources_after": {
            "balance": str(round(balance, 2)),
            "energy": energy,
            "time": time_left,
            "trust": trust,
            "slots": max(0, max_actions - len(steps)),
        },
        "totals": {
            "gross_inflow": str(round(inflow, 2)),
            "gross_outflow": str(round(outflow, 2)),
            "fees": str(round(fees, 2)),
        },
        "objective": {
            "target_outflow": str(round(target_outflow, 2)),
            "reached": goal_reached,
        },
        "limit_usage": {
            k: str(round(v, 2)) for k, v in limit_usage.items()
        },
        "limits": limits,
        "per_step": impacts,
        "steps": impacts,
        "resource_score": resource_score,
    }


def calculate_resource_score(
    balance: float,
    energy: int,
    time_left: int,
    trust: int,
    slots: int,
    outflow: float,
    fees: float,
    init_balance: float,
    init_energy: int,
    init_time: int,
    init_trust: int,
    max_actions: int,
) -> float:
    """Return a 0-100 score for resources preserved after reaching the goal."""
    def ratio(value: float, maximum: float) -> float:
        return max(0.0, min(1.0, value / max(1.0, maximum)))

    safe_outflow = max(1.0, outflow)
    fee_score = 1.0 - min(1.0, fees / safe_outflow)
    score = (
        ratio(balance, init_balance) * 20.0
        + ratio(energy, init_energy) * 15.0
        + ratio(time_left, init_time) * 15.0
        + ratio(trust, init_trust) * 25.0
        + fee_score * 15.0
        + ratio(slots, max_actions) * 10.0
    )
    return round(max(0.0, min(100.0, score)), 1)
