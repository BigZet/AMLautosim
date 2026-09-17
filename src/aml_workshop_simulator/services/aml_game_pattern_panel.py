"""Transparent teaching interpretations for competitive chain construction.

The panel is a Cartesian grid of 27 authored interpretations, not 27 human
experts or empirical fraud observations. Disagreement measures ambiguity of
educational pattern membership. It is never post-hoc probability rescaling.
"""

from collections import Counter
from itertools import product

PANEL_POLICY = {
    "version": "aml-game-pattern-panel-v1",
    "target": "observable_educational_pattern",
    "interpretations": 27,
    "time_windows": [2, 10, 60],
    "relative_amount_tolerances": [0.04, 0.12, 0.20],
    "structural_strictness": [0, 1, 2],
    "near_repetition_tolerance": 0.02,
    "meaning": "Probability of pattern membership across the explicitly authored teaching interpretations; not criminal probability or expert consensus",
    "rules": [
        "matched_relay",
        "repeated_fanout",
        "cash_conversion",
        "consolidation",
        "repeated_returns",
        "fragmentation",
    ],
    "structural_rules_survive_waiting": [
        "consolidation",
        "repeated_returns",
        "fragmentation",
    ],
}


def extract_panel_features(steps):
    times, now = [], 0
    for s in steps:
        now += s.get("interval_minutes") or 0
        times.append(now)
    incoming = [
        i for i, s in enumerate(steps) if s["card"]["code"] == "incoming_transfer"
    ]
    transfers = [s for s in steps if s["card"]["code"] == "card_transfer"]
    amounts = [float(s["amount"]) for s in transfers]
    recipients = Counter()
    for s in transfers:
        recipients[s["recipient_id"]] += float(s["amount"])
    cash = sum(
        float(s["amount"]) for s in steps if s["card"]["code"] == "cash_withdrawal"
    )
    outflow = sum(amounts) + cash
    precredit = sum(
        float(s["amount"])
        for i, s in enumerate(steps)
        if (not incoming or i < incoming[0])
        and s["card"]["code"] in ("card_transfer", "cash_withdrawal")
    )
    near_repeated = sum(
        any(i != j and abs(a - b) <= 0.02 * max(a, b) for j, b in enumerate(amounts))
        for i, a in enumerate(amounts)
    )
    result = dict(
        card_count=len(transfers),
        cash_share=cash / outflow if outflow else 0,
        sender_count=len({steps[i]["sender_id"] for i in incoming}),
        recipient_count=len(recipients),
        max_recipient_share=max(recipients.values(), default=0) / sum(amounts)
        if amounts
        else 0,
        near_repeated_share=near_repeated / len(amounts) if amounts else 0,
        precredit_outflow_share=precredit / outflow if outflow else 0,
        total_elapsed_minutes=now,
        incoming_count=len(incoming),
    )
    windows = [*PANEL_POLICY["time_windows"], "all"]
    for window in windows:
        result.update(
            {
                f"{name}_{window}": 0
                for name in (
                    "debit_episodes",
                    "fanout",
                    "cash",
                    "returns",
                    "small_split",
                )
            }
        )
        for tolerance in PANEL_POLICY["relative_amount_tolerances"]:
            result[f"matched_{window}_{int(tolerance * 100)}"] = 0
        for j, i in enumerate(incoming):
            stop = incoming[j + 1] if j + 1 < len(incoming) else len(steps)
            receipt = float(steps[i]["amount"])
            if receipt <= 0:
                raise ValueError("Incoming amount must be positive")
            debits = [
                s
                for k, s in enumerate(steps[i + 1 : stop], i + 1)
                if (window == "all" or times[k] - times[i] <= window)
                and s["card"]["code"] in ("card_transfer", "cash_withdrawal")
            ]
            cards = [s for s in debits if s["card"]["code"] == "card_transfer"]
            result[f"debit_episodes_{window}"] += bool(debits)
            result[f"fanout_{window}"] += len({s["recipient_id"] for s in cards}) >= 2
            result[f"cash_{window}"] += any(
                s["card"]["code"] == "cash_withdrawal" for s in debits
            )
            returned = sum(
                float(s["amount"])
                for s in cards
                if s["recipient_id"] == steps[i]["sender_id"]
            )
            result[f"returns_{window}"] += returned >= 0.5 * receipt
            result[f"small_split_{window}"] += len(cards) >= 2 and all(
                float(s["amount"]) <= 0.70 * receipt for s in cards
            )
            for tolerance in PANEL_POLICY["relative_amount_tolerances"]:
                result[f"matched_{window}_{int(tolerance * 100)}"] += any(
                    abs(float(s["amount"]) / receipt - 1) <= tolerance for s in debits
                )
    return result


def assess_panel(features):
    f = features
    votes, matched_rules = [], Counter()
    for window, tolerance, strict in product(
        PANEL_POLICY["time_windows"],
        PANEL_POLICY["relative_amount_tolerances"],
        PANEL_POLICY["structural_strictness"],
    ):
        rules = {
            "matched_relay": f[f"matched_{window}_{int(tolerance * 100)}"] >= 2,
            "repeated_fanout": f[f"fanout_{window}"] >= 2
            and f["recipient_count"] >= 3
            and f["precredit_outflow_share"] < [0.30, 0.25, 0.20][strict],
            "cash_conversion": f[f"cash_{window}"] >= 1
            and f[f"debit_episodes_{window}"] >= 2
            and f["cash_share"] >= [0.15, 0.225, 0.30][strict],
            "consolidation": f["sender_count"] >= [2, 2, 3][strict]
            and f["max_recipient_share"] >= [0.72, 0.82, 0.92][strict]
            and f["precredit_outflow_share"] < [0.25, 0.20, 0.15][strict],
            "repeated_returns": f["returns_all"] >= [2, 2, 3][strict],
            "fragmentation": f["card_count"] >= 7
            and f["small_split_all"] >= 2
            and f["near_repeated_share"] >= [0.65, 0.75, 0.85][strict],
        }
        votes.append(int(any(rules.values())))
        matched_rules.update(k for k, value in rules.items() if value)
    probability = sum(votes) / len(votes)
    return dict(
        positive_votes=sum(votes),
        panel_size=len(votes),
        target_probability=probability,
        band="low" if probability < 0.1 else "high" if probability >= 0.9 else "grey",
        rule_support=dict(matched_rules),
    )
