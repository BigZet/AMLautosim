"""Fine teaching-interpretation grid with smooth amount comparisons.

603 explicitly authored interpretations = three temporal windows x 201
sensitivity settings. They are neither human reviewers nor measured prevalence.
The finer grid prevents a one-ruble threshold crossing moving a third of votes.
"""

from collections import Counter
from src.aml_workshop_simulator.services.aml_game_pattern_panel import (
    extract_panel_features as extract_base,
)

PANEL_POLICY = {
    "version": "aml-game-pattern-panel-v2.1",
    "target": "observable_educational_pattern",
    "time_windows": [2, 10, 60],
    "sensitivity_settings": 201,
    "interpretations": 603,
    "amount_tolerance_range": [0.04, 0.20],
    "near_repetition_scale": 0.05,
    "small_payment_ratio_range": [0.65, 0.80],
    "return_ratio_range": [0.45, 0.60],
    "rules": [
        "matched_relay",
        "repeated_fanout",
        "cash_conversion",
        "consolidation",
        "repeated_returns",
        "fragmentation",
    ],
    "meaning": "Probability across a disclosed teaching-interpretation grid; not criminal probability or human-expert consensus",
    "structural_rules_survive_waiting": [
        "consolidation",
        "repeated_returns",
        "fragmentation",
    ],
}


def extract_panel_features(steps):
    base = extract_base(steps)
    # Keep factual aggregates; replace the coarse thresholded match counters.
    features = {
        k: v
        for k, v in base.items()
        if not k.startswith("matched_") and k != "near_repeated_share"
    }
    amounts = [
        float(s["amount"]) for s in steps if s["card"]["code"] == "card_transfer"
    ]
    similarities = [
        max(
            (
                max(0.0, 1 - abs(a - b) / (0.05 * max(a, b)))
                for j, b in enumerate(amounts)
                if i != j
            ),
            default=0.0,
        )
        for i, a in enumerate(amounts)
    ]
    features["amount_repetition_strength"] = (
        sum(similarities) / len(similarities) if similarities else 0.0
    )
    times, elapsed = [], 0
    for s in steps:
        elapsed += s.get("interval_minutes") or 0
        times.append(elapsed)
    credits = [
        i for i, s in enumerate(steps) if s["card"]["code"] == "incoming_transfer"
    ]
    split_ratios, return_ratios = [], []
    for n, start in enumerate(credits):
        stop = credits[n + 1] if n + 1 < len(credits) else len(steps)
        receipt = float(steps[start]["amount"])
        cards = [
            s for s in steps[start + 1 : stop] if s["card"]["code"] == "card_transfer"
        ]
        split_ratios.append(
            max(float(s["amount"]) / receipt for s in cards) if len(cards) >= 2 else 2.0
        )
        return_ratios.append(
            sum(
                float(s["amount"]) / receipt
                for s in cards
                if s["recipient_id"] == steps[start]["sender_id"]
            )
        )
    features["second_split_ratio_all"] = (
        sorted(split_ratios)[1] if len(split_ratios) >= 2 else 2.0
    )
    ordered_returns = sorted(return_ratios, reverse=True)
    features["second_return_ratio_all"] = (
        ordered_returns[1] if len(ordered_returns) >= 2 else 0.0
    )
    features["third_return_ratio_all"] = (
        ordered_returns[2] if len(ordered_returns) >= 3 else 0.0
    )
    for window in PANEL_POLICY["time_windows"]:
        errors = []
        for n, start in enumerate(credits):
            stop = credits[n + 1] if n + 1 < len(credits) else len(steps)
            receipt = float(steps[start]["amount"])
            errors.append(
                min(
                    (
                        abs(float(s["amount"]) / receipt - 1)
                        for i, s in enumerate(steps[start + 1 : stop], start + 1)
                        if times[i] - times[start] <= window
                        and s["card"]["code"] in ("card_transfer", "cash_withdrawal")
                    ),
                    default=2.0,
                )
            )
        features[f"second_match_error_{window}"] = (
            sorted(errors)[1] if len(errors) >= 2 else 2.0
        )
    return features


def assess_panel(f):
    votes, supports = 0, Counter()
    for window in PANEL_POLICY["time_windows"]:
        for i in range(PANEL_POLICY["sensitivity_settings"]):
            strict = i / (PANEL_POLICY["sensitivity_settings"] - 1)
            rules = {
                "matched_relay": f[f"second_match_error_{window}"]
                <= 0.20 - 0.16 * strict,
                "repeated_fanout": f[f"fanout_{window}"] >= 2
                and f["recipient_count"] >= 3
                and f["precredit_outflow_share"] < 0.30 - 0.10 * strict,
                "cash_conversion": f[f"cash_{window}"] >= 1
                and f[f"debit_episodes_{window}"] >= 2
                and f["cash_share"] >= 0.15 + 0.15 * strict,
                "consolidation": f["sender_count"] >= (2 if strict <= 2 / 3 else 3)
                and f["max_recipient_share"] >= 0.72 + 0.20 * strict
                and f["precredit_outflow_share"] < 0.25 - 0.10 * strict,
                "repeated_returns": f[
                    "second_return_ratio_all"
                    if strict <= 2 / 3
                    else "third_return_ratio_all"
                ]
                >= 0.45 + 0.15 * strict,
                "fragmentation": f["card_count"] >= 7
                and f["second_split_ratio_all"] <= 0.80 - 0.15 * strict
                and f["amount_repetition_strength"] >= 0.65 + 0.20 * strict,
            }
            votes += any(rules.values())
            supports.update(k for k, value in rules.items() if value)
    probability = votes / PANEL_POLICY["interpretations"]
    return dict(
        positive_votes=votes,
        panel_size=PANEL_POLICY["interpretations"],
        target_probability=probability,
        band="low" if probability < 0.1 else "high" if probability >= 0.9 else "grey",
        rule_support=dict(supports),
    )
