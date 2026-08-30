from __future__ import annotations

import math
from typing import Any

from src.aml_workshop_simulator.core.game_config import base_game_config, load_config
from src.aml_workshop_simulator.domain.catalog import CARD_CATALOG
from src.aml_workshop_simulator.domain.round_policy import RoundPolicy
from src.aml_workshop_simulator.domain.rules import card_spec_from_catalog, money
from src.aml_workshop_simulator.services.configuration import snapshot_specs


def _get_card_code(step: dict[str, Any]) -> str:
    card = step.get("card")
    if isinstance(card, dict):
        return card.get("code") or ""
    return step.get("card_code") or ""


def extract_catboost_features(
    steps: list[dict[str, Any]], round_config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    Transforms a sequence of AML scenario steps into a structured tabular feature dictionary
    formatted specifically for training and inference with CatBoostClassifier / CatBoostRegressor.

    Features include aggregated financial metrics, behavioral risk ratios, sequence patterns,
    and categorical descriptors.
    """
    if not steps:
        return {
            "num_steps": 0,
            "total_turnover": 0.0,
            "total_inflow": 0.0,
            "total_outflow": 0.0,
            "net_turnover": 0.0,
            "outflow_to_inflow_ratio": 0.0,
            "fees_total": 0.0,
            "fees_ratio": 0.0,
            "cash_inflow_sum": 0.0,
            "cash_outflow_sum": 0.0,
            "cash_turnover_ratio": 0.0,
            "anonymous_recipient_turnover": 0.0,
            "anonymous_recipient_ratio": 0.0,
            "night_operations_count": 0,
            "night_operations_ratio": 0.0,
            "rapid_velocity_count": 0,
            "rapid_velocity_ratio": 0.0,
            "without_docs_large_sum": 0.0,
            "without_docs_ratio": 0.0,
            "avg_step_amount": 0.0,
            "max_step_amount": 0.0,
            "std_step_amount": 0.0,
            "max_frequency_single_step": 0,
            "repeated_amount_count": 0,
            "rapid_credit_to_debit_count": 0,
            "unique_channels_count": 0,
            "unique_cards_count": 0,
            # Categoricals
            "primary_channel": "none",
            "primary_category": "none",
            "most_frequent_card": "none",
            "has_cash": 0,
        }

    config = round_config or base_game_config()
    risk_rules = (config.get("scoring") or {}).get("rules") or base_game_config()[
        "scoring"
    ]["rules"]
    specs = snapshot_specs(config) or {
        (entry["code"], entry["version"]): card_spec_from_catalog(entry, index)
        for index, entry in enumerate(CARD_CATALOG, start=1)
    }
    policy = RoundPolicy.from_config(config, specs)

    def spec_for(step):
        code = _get_card_code(step)
        version = (step.get("card") or {}).get("version")
        candidates = [
            spec
            for key, spec in specs.items()
            if key[0] == code and (version is None or key[1] == version)
        ]
        if not candidates:
            raise ValueError(f"unsupported operation code/version: {code} v{version}")
        spec = max(candidates, key=lambda item: item.version)
        operation = policy.for_card(spec.key)
        return spec.with_overrides(operation.overrides if operation else None)

    total_inflow = 0.0
    total_outflow = 0.0
    fees_total = 0.0
    cash_inflow = 0.0
    cash_outflow = 0.0
    anon_recipient_sum = 0.0
    night_ops = 0
    rapid_velocity_ops = 0
    without_docs_large_sum = 0.0

    amounts: list[float] = []
    card_counts: dict[str, int] = {}
    channel_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}

    for step in steps:
        card_code = _get_card_code(step)
        spec = spec_for(step)

        amount = float(step.get("amount", 0.0))
        freq = int(step.get("frequency", 1))
        gross = amount * freq

        amounts.append(amount)
        card_counts[card_code] = card_counts.get(card_code, 0) + freq

        # Resolve omitted context from the same card contract used by the game.
        ctx = {**spec.context_defaults, "channel": spec.channels[0]}
        ctx.update({key: step[key] for key in ctx if key in step})
        ctx.update(step.get("context") or {})
        recipient_type = ctx["recipient_type"]
        time_of_day = ctx["time_of_day"]
        velocity = ctx["velocity"]
        channel = ctx["channel"]
        has_docs = bool(ctx["has_documents"])
        channel_counts[channel] = channel_counts.get(channel, 0) + 1
        fees_total += float(money(money(amount) * freq * spec.fee_rate))

        if spec.flow == "credit":
            total_inflow += gross
            if spec.quota_category == "cash":
                cash_inflow += gross
        elif spec.flow == "debit":
            total_outflow += gross
            if spec.quota_category == "cash":
                cash_outflow += gross
        category = load_config("synthetic_data.json")["feature_categories"].get(
            spec.code, spec.quota_category or spec.category
        )
        category_counts[category] = category_counts.get(category, 0) + 1

        if recipient_type == "anonymous_wallet":
            anon_recipient_sum += gross
        if time_of_day == "night":
            night_ops += 1
        if velocity == "rapid":
            rapid_velocity_ops += 1
        if not has_docs and gross >= float(risk_rules["documents"]["minimum_gross"]):
            without_docs_large_sum += gross

    total_turnover = total_inflow + total_outflow
    num_steps = len(steps)

    # Statistical measures on step amounts
    avg_amount = sum(amounts) / max(1, num_steps)
    max_amount = max(amounts) if amounts else 0.0
    var_amount = sum((x - avg_amount) ** 2 for x in amounts) / max(1, num_steps)
    std_amount = math.sqrt(var_amount)

    # Sequence analysis
    repeated_amounts_count = 0
    amt_counts: dict[float, int] = {}
    for a in amounts:
        if a >= float(risk_rules["sequence"]["repeated_min_amount"]):
            amt_counts[a] = amt_counts.get(a, 0) + 1
    repeated_amounts_count = sum(1 for c in amt_counts.values() if c > 1)

    rapid_credit_to_debit = 0
    for idx in range(1, num_steps):
        prev_step = steps[idx - 1]
        curr_step = steps[idx]
        prev_gross = float(prev_step.get("amount", 0)) * int(
            prev_step.get("frequency", 1)
        )
        curr_gross = float(curr_step.get("amount", 0)) * int(
            curr_step.get("frequency", 1)
        )
        if spec_for(prev_step).flow == "credit" and spec_for(curr_step).flow == "debit":
            if prev_gross > 0 and curr_gross >= prev_gross * float(
                risk_rules["sequence"]["turnover_ratio"]
            ):
                rapid_credit_to_debit += 1

    # Categorical dominant values
    primary_channel = (
        max(channel_counts.items(), key=lambda x: x[1])[0] if channel_counts else "none"
    )
    primary_category = (
        max(category_counts.items(), key=lambda x: x[1])[0]
        if category_counts
        else "none"
    )
    most_frequent_card = (
        max(card_counts.items(), key=lambda x: x[1])[0] if card_counts else "none"
    )

    return {
        "num_steps": num_steps,
        "total_turnover": round(total_turnover, 2),
        "total_inflow": round(total_inflow, 2),
        "total_outflow": round(total_outflow, 2),
        "net_turnover": round(total_inflow - total_outflow, 2),
        "outflow_to_inflow_ratio": round(total_outflow / max(1.0, total_inflow), 4),
        "fees_total": round(fees_total, 2),
        "fees_ratio": round(fees_total / max(1.0, total_turnover), 4),
        "cash_inflow_sum": round(cash_inflow, 2),
        "cash_outflow_sum": round(cash_outflow, 2),
        "cash_turnover_ratio": round(
            (cash_inflow + cash_outflow) / max(1.0, total_turnover), 4
        ),
        "anonymous_recipient_turnover": round(anon_recipient_sum, 2),
        "anonymous_recipient_ratio": round(
            anon_recipient_sum / max(1.0, total_turnover), 4
        ),
        "night_operations_count": night_ops,
        "night_operations_ratio": round(night_ops / max(1, num_steps), 4),
        "rapid_velocity_count": rapid_velocity_ops,
        "rapid_velocity_ratio": round(rapid_velocity_ops / max(1, num_steps), 4),
        "without_docs_large_sum": round(without_docs_large_sum, 2),
        "without_docs_ratio": round(
            without_docs_large_sum / max(1.0, total_turnover), 4
        ),
        "avg_step_amount": round(avg_amount, 2),
        "max_step_amount": round(max_amount, 2),
        "std_step_amount": round(std_amount, 2),
        "max_frequency_single_step": max(
            (int(s.get("frequency", 1)) for s in steps), default=0
        ),
        "repeated_amount_count": repeated_amounts_count,
        "rapid_credit_to_debit_count": rapid_credit_to_debit,
        "unique_channels_count": len(channel_counts),
        "unique_cards_count": len(card_counts),
        # Categoricals (CatBoost handles these natively with cat_features)
        "primary_channel": primary_channel,
        "primary_category": primary_category,
        "most_frequent_card": most_frequent_card,
        "has_cash": 1 if (cash_inflow + cash_outflow) > 0 else 0,
    }


def get_catboost_feature_names() -> list[str]:
    """Return the ordered list of feature names for CatBoost."""
    dummy = extract_catboost_features([])
    return list(dummy.keys())


def get_catboost_categorical_feature_names() -> list[str]:
    """Return the list of categorical feature names to pass to CatBoostPool / cat_features."""
    return ["primary_channel", "primary_category", "most_frequent_card"]
