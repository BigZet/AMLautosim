"""Versioned risk engine (`risk-rules-v2`) and leaderboard formula.

Everything is a pure function of `steps + round snapshot + card versions`; no
clock, randomness or mutable catalog is consulted, so the same input always
produces the same result. All arithmetic uses `Decimal`.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from src.aml_workshop_simulator.core.enums import RiskLabel
from src.aml_workshop_simulator.core.game_config import base_game_config
from src.aml_workshop_simulator.domain.round_policy import RoundPolicy
from src.aml_workshop_simulator.domain.rules import (
    CardSpec,
    RoundRules,
    action_detail_effects,
    money,
)

SCORING_VERSION = "risk-rules-v2"
LEADERBOARD_VERSION = "leaderboard-v2"
EXPLANATION_SCHEMA_VERSION = 2

SCORE = Decimal("0.01")
ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")

DISCLAIMER = "Учебная модель; результат не является AML-решением"

CREDIT_FLOW = "credit"
DEBIT_FLOW = "debit"


def _score(value: Decimal) -> Decimal:
    return value.quantize(SCORE, rounding=ROUND_HALF_EVEN)


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return max(low, min(high, value))


def _factor(
    code: str,
    category: str,
    points: Decimal,
    description: str,
    step_id: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "code": code,
        "category": category,
        "points": str(_score(points)),
        "description": description,
        "evidence": evidence or {},
    }


def _points(factor: dict[str, Any]) -> Decimal:
    return Decimal(factor["points"])


def score_scenario(
    steps: Sequence[dict[str, Any]],
    card_specs: dict[tuple[str, int], CardSpec],
    game_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Risk score, label and explanation for one canonical chain."""
    config = game_config or {}
    scoring_cfg = {**base_game_config()["scoring"], **config.get("scoring", {})}
    rules = scoring_cfg["rules"]
    review_threshold = Decimal(str(scoring_cfg["review_threshold"]))
    suspicious_threshold = Decimal(str(scoring_cfg["suspicious_threshold"]))
    policy = RoundPolicy.from_config(game_config, card_specs)

    factors: list[dict[str, Any]] = []

    for step in steps:
        step_id = str(step["step_id"])
        spec = card_specs[(step["card"]["code"], int(step["card"]["version"]))]
        operation = policy.for_card(spec.key)
        spec = spec.with_overrides(operation.overrides if operation else None)
        amount = money(step["amount"])
        frequency = int(step["frequency"])
        gross = money(amount * frequency)
        context = step["context"]
        details = dict(step.get("action_details") or {})

        factors.append(
            _factor(
                f"card:{spec.code}",
                "card",
                spec.risk_weight,
                f"Базовый риск операции «{spec.title}»",
                step_id,
                {"card_code": spec.code, "card_version": spec.version},
            )
        )
        factors.append(
            _factor(
                "amount:absolute",
                "amount",
                _clamp(
                    amount / Decimal(str(rules["amount_divisor"])),
                    ZERO,
                    Decimal(str(rules["amount_max_points"])),
                ),
                "Крупные суммы повышают приоритет проверки",
                step_id,
                {"amount": str(amount)},
            )
        )
        factors.append(
            _factor(
                "frequency:repeats",
                "frequency",
                Decimal(max(0, frequency - 1))
                * Decimal(str(rules["extra_repeat_points"])),
                "Повторы могут быть похожи на дробление операции",
                step_id,
                {"frequency": frequency},
            )
        )
        factors.append(
            _factor(
                f"recipient:{context['recipient_type']}",
                "context",
                Decimal(rules["recipient_points"][context["recipient_type"]]),
                "Неизвестный или анонимный получатель повышает неопределенность",
                step_id,
            )
        )
        factors.append(
            _factor(
                f"time_of_day:{context['time_of_day']}",
                "context",
                Decimal(rules["time_of_day_points"][context["time_of_day"]]),
                "Нетипичное время операции может потребовать проверки",
                step_id,
            )
        )
        factors.append(
            _factor(
                f"velocity:{context['velocity']}",
                "context",
                Decimal(rules["velocity_points"][context["velocity"]]),
                "Темп повторов влияет на сходство с автоматизированной цепочкой",
                step_id,
            )
        )
        factors.append(
            _factor(
                f"channel:{context['channel']}",
                "context",
                Decimal(rules["channel_points"][context["channel"]]),
                "Канал операции влияет на доступность подтверждающего контекста",
                step_id,
            )
        )
        factors.append(
            _factor(
                "documents:present" if context["has_documents"] else "documents:absent",
                "context",
                _document_points(
                    gross, bool(context["has_documents"]), rules["documents"]
                ),
                (
                    "Подтверждающие документы снижают неопределенность операции"
                    if context["has_documents"]
                    else "Отсутствие документов повышает неопределенность операции"
                ),
                step_id,
            )
        )

        for detail in action_detail_effects(spec, details)["factors"]:
            factors.append(
                _factor(
                    f"detail:{spec.code}:{detail['field_key']}:{detail['value']}",
                    "action_detail",
                    detail["risk_points"],
                    detail["description"]
                    or f"{detail['field_label']}: {detail['value_label']}",
                    step_id,
                )
            )

    sequence_factors = _sequence_factors(steps, card_specs, rules["sequence"])
    factors.extend(sequence_factors)

    raw = sum((_points(item) for item in factors), ZERO)
    step_count = max(1, len(steps))
    normalized = _score(_clamp(raw / Decimal(step_count), ZERO, HUNDRED))

    if normalized >= suspicious_threshold:
        label = RiskLabel.suspicious
    elif normalized >= review_threshold:
        label = RiskLabel.review
    else:
        label = RiskLabel.normal

    risk_factors = sorted(
        (item for item in factors if _points(item) > ZERO),
        key=lambda item: (-_points(item), item["code"], item["step_id"] or ""),
    )
    protective_factors = sorted(
        (item for item in factors if _points(item) < ZERO),
        key=lambda item: (_points(item), item["code"], item["step_id"] or ""),
    )

    explanation = {
        "schema_version": EXPLANATION_SCHEMA_VERSION,
        "scoring_version": SCORING_VERSION,
        "top_risk_factors": risk_factors[: rules["explanation_factor_limit"]],
        "protective_factors": protective_factors[: rules["explanation_factor_limit"]],
        "sequence_factors": sequence_factors,
        "all_factors": factors,
        "raw_score": str(_score(raw)),
        "normalized_score": str(normalized),
        "step_count": len(steps),
        "thresholds": {
            "review": str(review_threshold),
            "suspicious": str(suspicious_threshold),
        },
        "disclaimer": DISCLAIMER,
    }
    return {
        "risk_score": normalized,
        "risk_label": label,
        "explanation": explanation,
    }


def _document_points(
    gross: Decimal, has_documents: bool, rules: dict[str, Any]
) -> Decimal:
    size = "large" if gross >= Decimal(str(rules["minimum_gross"])) else "small"
    presence = "present" if has_documents else "absent"
    return Decimal(rules[f"{presence}_{size}"])


def _sequence_factors(
    steps: Sequence[dict[str, Any]],
    card_specs: dict[tuple[str, int], CardSpec],
    rules: dict[str, Any],
) -> list[dict[str, Any]]:
    factors: list[dict[str, Any]] = []

    amounts: dict[Decimal, int] = {}
    for step in steps:
        amount = money(step["amount"])
        if amount >= Decimal(str(rules["repeated_min_amount"])):
            amounts[amount] = amounts.get(amount, 0) + 1
    repeated = sum(1 for count in amounts.values() if count > 1)
    if repeated:
        factors.append(
            _factor(
                "sequence:repeated_amounts",
                "sequence",
                min(
                    Decimal(str(rules["repeated_max_points"])),
                    Decimal(repeated) * Decimal(str(rules["repeated_points"])),
                ),
                "Одинаковые суммы в разных шагах похожи на шаблонную цепочку",
                None,
                {"repeated_amount_groups": repeated},
            )
        )

    def spec_of(step: dict[str, Any]) -> CardSpec:
        return card_specs[(step["card"]["code"], int(step["card"]["version"]))]

    for index in range(1, len(steps)):
        previous, current = steps[index - 1], steps[index]
        previous_spec, current_spec = spec_of(previous), spec_of(current)
        previous_gross = money(money(previous["amount"]) * int(previous["frequency"]))
        current_gross = money(money(current["amount"]) * int(current["frequency"]))
        if (
            previous_spec.flow == CREDIT_FLOW
            and current_spec.flow == DEBIT_FLOW
            and previous_gross > ZERO
            and current_gross >= previous_gross * Decimal(str(rules["turnover_ratio"]))
        ):
            factors.append(
                _factor(
                    "sequence:rapid_turnover",
                    "sequence",
                    Decimal(str(rules["turnover_points"])),
                    "Большая часть поступления быстро уходит следующим действием",
                    str(current["step_id"]),
                )
            )

    return factors


# --------------------------------------------------------------------------
# Leaderboard formula
# --------------------------------------------------------------------------


def resource_score(
    snapshot: dict[str, Any], game_config: dict[str, Any] | None
) -> Decimal:
    """Normalised resource efficiency in `0..100`."""
    config = game_config or {}
    rules = RoundRules.from_config(config)
    weights_cfg = (config.get("leaderboard") or {}).get("resource_weights")
    if weights_cfg is None:
        weights_cfg = base_game_config()["leaderboard"]["resource_weights"]
    weights = {key: Decimal(str(value)) for key, value in weights_cfg.items()}

    after = snapshot.get("resources_after", {})
    totals = snapshot.get("totals", {})

    def ratio(value: Decimal, maximum: Decimal) -> Decimal:
        if maximum <= ZERO:
            return ONE
        return _clamp(value / maximum, ZERO, ONE)

    outflow = money(totals.get("gross_outflow", "0"))
    fees = money(totals.get("fees", "0"))
    fee_ratio = ONE - _clamp(fees / max(outflow, ONE), ZERO, ONE)

    components = {
        "balance": ratio(money(after.get("balance", "0")), rules.initial_balance),
        "energy": ratio(
            Decimal(int(after.get("energy", 0))), Decimal(rules.initial_energy)
        ),
        "time": ratio(Decimal(int(after.get("time", 0))), Decimal(rules.initial_time)),
        "fees": fee_ratio,
        "available_steps": ratio(
            Decimal(int(after.get("available_steps", 0))), Decimal(rules.max_actions)
        ),
    }
    total = sum((weights[key] * value for key, value in components.items()), ZERO)
    return _score(_clamp(HUNDRED * total, ZERO, HUNDRED))


def leaderboard_scores(
    risk: Decimal,
    resources: Decimal,
    game_config: dict[str, Any] | None,
) -> dict[str, Decimal]:
    """Stealth and composite game score from the round's leaderboard weights."""
    config = (game_config or {}).get("leaderboard", {}) or {}
    weights = config.get("weights") or base_game_config()["leaderboard"]["weights"]
    stealth_weight = Decimal(str(weights["stealth"]))
    resource_weight = Decimal(str(weights["resources"]))
    stealth = _score(_clamp(HUNDRED - risk, ZERO, HUNDRED))
    game = _score(
        _clamp(stealth * stealth_weight + resources * resource_weight, ZERO, HUNDRED)
    )
    return {"stealth_score": stealth, "resource_score": resources, "game_score": game}


def weights_sum_to_one(game_config: dict[str, Any]) -> bool:
    board = game_config.get("leaderboard") or {}
    weights = board.get("weights") or {}
    total = sum((Decimal(str(value)) for value in weights.values()), ZERO)
    resource_weights = board.get("resource_weights") or {}
    resource_total = sum(
        (Decimal(str(value)) for value in resource_weights.values()), ZERO
    )
    return total == ONE and resource_total == ONE
