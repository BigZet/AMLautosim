"""Versioned risk engine (`risk-rules-v3`) and leaderboard formula.

Everything is a pure function of `steps + round snapshot + card versions`; no
clock, randomness or mutable catalog is consulted, so the same input always
produces the same result. All arithmetic uses `Decimal`.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from src.aml_workshop_simulator.domain.contract_versions import (
    require_legacy_contract,
)
from src.aml_workshop_simulator.core.enums import RiskLabel
from src.aml_workshop_simulator.domain.round_policy import RoundPolicy
from src.aml_workshop_simulator.domain.rules import (
    CardSpec,
    RoundRules,
    action_detail_effects,
    money,
)

SCORING_VERSION = "risk-rules-v3"
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
    require_legacy_contract(game_config)
    return _score_validated(steps, card_specs, game_config)


def _score_validated(steps, card_specs, game_config, *, timeline=None):
    config = game_config or {}
    scoring_cfg = config["scoring"]
    rules = scoring_cfg["rules"]
    review_threshold = Decimal(str(scoring_cfg["review_threshold"]))
    suspicious_threshold = Decimal(str(scoring_cfg["suspicious_threshold"]))
    policy = RoundPolicy.from_config(game_config, card_specs)

    factors: list[dict[str, Any]] = []

    for index, step in enumerate(steps):
        step_id = str(step["step_id"])
        spec = card_specs[(step["card"]["code"], int(step["card"]["version"]))]
        operation = policy.for_card(spec.key)
        spec = spec.with_overrides(operation.overrides if operation else None)
        amount = money(step["amount"])
        gross = amount
        context = dict(step["context"])
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
        context_rules = {
            "recipient_type": ("recipient", "recipient_points", "Профиль получателя"),
            "time_of_day": ("time_of_day", "time_of_day_points", "Время операции"),
            "velocity": ("velocity", "velocity_points", "Темп операции"),
            "channel": ("channel", "channel_points", "Канал операции"),
        }
        applicable = {f["key"] for f in spec.context_fields}
        if timeline is not None:
            timing = timeline[index]
            applicable = {"time_of_day"}
            context["time_of_day"] = timing["time_of_day"]
            if timing["pace"] is not None:
                applicable.add("velocity")
                context["velocity"] = timing["pace"]
        if spec.channels:
            applicable.add("channel")
        for key, (code, rule, description) in context_rules.items():
            if key in applicable:
                value = context[key]
                factors.append(
                    _factor(
                        f"{code}:{value}",
                        "context",
                        Decimal(rules[rule][value]),
                        description,
                        step_id,
                    )
                )
        adjustment = rules["amount_adjustment"]
        if gross >= Decimal(str(adjustment["minimum_gross"])):
            factors.append(
                _factor(
                    "amount:adjustment",
                    "amount",
                    Decimal(str(adjustment["risk_points"])),
                    "Балансировочная поправка для суммы от "
                    + str(adjustment["minimum_gross"])
                    + " ₽",
                    step_id,
                    {
                        "amount": str(gross),
                        "minimum_gross": str(adjustment["minimum_gross"]),
                    },
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

    sequence_factors = _sequence_factors(
        steps, card_specs, rules["sequence"], timed=timeline is not None
    )
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
    if timeline is not None:
        explanation["scoring_version"] = "expanded-scoring-stage03-v1"
        explanation["timeline_version"] = "operation-timeline-v1"
    return {
        "risk_score": normalized,
        "risk_label": label,
        "explanation": explanation,
    }


def _sequence_factors(
    steps: Sequence[dict[str, Any]],
    card_specs: dict[tuple[str, int], CardSpec],
    rules: dict[str, Any],
    *,
    timed=False,
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
        previous_gross = money(money(previous["amount"]))
        current_gross = money(money(current["amount"]))
        if (
            (not timed or current.get("interval_minutes") == 1)
            and previous_spec.flow == CREDIT_FLOW
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
    weights_cfg = config["leaderboard"]["resource_weights"]
    weights = {key: Decimal(str(value)) for key, value in weights_cfg.items()}

    after = snapshot.get("resources_after", {})
    totals = snapshot.get("totals", {})

    def ratio(value: Decimal, maximum: Decimal) -> Decimal:
        if maximum <= ZERO:
            return ONE
        return _clamp(value / maximum, ZERO, ONE)

    outflow = money(totals.get("target_outflow", totals.get("gross_outflow", "0")))
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
    weights = game_config["leaderboard"]["weights"]
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


AML_LEADERBOARD_VERSION = "leaderboard-aml-probability-v1"


def probability_leaderboard_scores(probability, resources, game_config):
    """Apply existing resource weights with unrounded calibrated probability."""
    probability = Decimal(str(probability))
    if not probability.is_finite() or not ZERO <= probability <= ONE:
        raise ValueError("AML probability must be finite and in [0, 1]")
    weights = game_config["leaderboard"]["weights"]
    stealth = HUNDRED * (ONE - probability)
    game = stealth * Decimal(str(weights["stealth"])) + resources * Decimal(
        str(weights["resources"])
    )
    return {
        "stealth_score": _score(stealth),
        "resource_score": resources,
        "game_score": _score(_clamp(game, ZERO, HUNDRED)),
    }
