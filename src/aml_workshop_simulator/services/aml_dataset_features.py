"""Versioned, scoring-independent features for canonical game scenarios.

This is the single v1 extraction entrypoint for offline data and future inference.
The deferred legacy sample extractor is deliberately left compatible.
"""

from collections import Counter
from statistics import pstdev

from src.aml_workshop_simulator.domain.rules import money
from src.aml_workshop_simulator.services.configuration import snapshot_specs

FEATURE_VERSION = "aml-observable-v1"
CATEGORICAL_FEATURES = ["income_basis"]


def extract_features(steps: list[dict], config: dict) -> dict:
    specs = snapshot_specs(config)
    if not specs or not steps:
        raise ValueError("Features require nonempty canonical steps and card snapshots")
    codes = [s["card"]["code"] for s in steps]
    amounts = [float(money(s["amount"])) for s in steps]
    flows = [specs[(s["card"]["code"], s["card"]["version"])].flow for s in steps]
    credits = [i for i, flow in enumerate(flows) if flow == "credit"]
    debits = [i for i, flow in enumerate(flows) if flow == "debit"]
    incoming = [s for s in steps if s["card"]["code"] == "incoming_transfer"]
    transfers = [s for s in steps if s["card"]["code"] == "card_transfer"]
    contexts = [s["context"] for s in steps]
    inflow = sum(amounts[i] for i in credits)
    outflow = sum(amounts[i] for i in debits)
    turnover = inflow + outflow
    available = float(config["resources"]["initial_balance"]) + inflow
    rapid_debits = sum(contexts[i].get("velocity") == "rapid" for i in debits)
    transitions = [
        i for i in range(1, len(steps)) if flows[i - 1 : i + 1] == ["credit", "debit"]
    ]
    rapid = [i for i in transitions if contexts[i].get("velocity") == "rapid"]
    incoming_rapid = [i for i in rapid if codes[i - 1] == "incoming_transfer"]
    cash_transitions = [i for i in transitions if codes[i] == "cash_withdrawal"]
    debit_counts = Counter(amounts[i] for i in debits)
    repeated = sum(n - 1 for n in debit_counts.values())
    cash = sum(a for a, code in zip(amounts, codes) if code == "cash_withdrawal")
    fees = sum(
        float(
            money(
                money(s["amount"])
                * specs[(s["card"]["code"], s["card"]["version"])].fee_rate
            )
        )
        for s in steps
    )
    longest = run = 0
    for flow in flows:
        run = run + 1 if flow == "debit" else 0
        longest = max(longest, run)
    features = {
        "num_steps": len(steps),
        "total_inflow": inflow,
        "total_outflow": outflow,
        "total_turnover": turnover,
        "net_turnover": inflow - outflow,
        "fees_total": fees,
        "fees_ratio": fees / max(turnover, 1),
        "outflow_to_available_ratio": outflow / max(available, 1),
        "has_no_inflow": int(not credits),
        "outflow_to_inflow_ratio": outflow / inflow if inflow else 0.0,
        "cash_outflow_sum": cash,
        "cash_outflow_ratio": cash / max(outflow, 1),
        "avg_step_amount": turnover / len(steps),
        "max_step_amount": max(amounts),
        "std_step_amount": pstdev(amounts),
        "unique_channels_count": len(
            {c["channel"] for c in contexts if "channel" in c}
        ),
        "unique_cards_count": len(set(codes)),
        "max_consecutive_debits": longest,
        "credit_to_debit_count": len(transitions),
        "credit_to_cash_count": len(cash_transitions),
        "rapid_credit_to_debit_context_count": len(rapid),
        "rapid_credit_debit_ratio": len(incoming_rapid) / max(len(incoming), 1),
        "rapid_cash_after_credit_ratio": sum(
            codes[i] == "cash_withdrawal" for i in incoming_rapid
        )
        / max(len(incoming), 1),
        "rapid_debit_ratio": rapid_debits / max(len(debits), 1),
        "repeated_debit_ratio": repeated / max(len(debits), 1),
        "unknown_sender_ratio": sum(
            s["action_details"]["sender_relationship"] != "regular_sender"
            for s in incoming
        )
        / max(len(incoming), 1),
        "anonymous_recipient_ratio": sum(
            s["context"]["recipient_type"] == "anonymous_wallet" for s in transfers
        )
        / max(len(transfers), 1),
        "new_recipient_ratio": sum(
            s["context"]["recipient_type"] == "new_counterparty" for s in transfers
        )
        / max(len(transfers), 1),
        "income_basis": next(
            (
                s["action_details"]["income_basis"]
                for s in steps
                if s["card"]["code"] == "salary"
            ),
            "none",
        ),
    }
    for name, values, observed in [
        (
            "card",
            ["salary", "incoming_transfer", "card_transfer", "cash_withdrawal"],
            codes,
        ),
        (
            "source",
            ["domestic_bank", "foreign_bank_kg", "crypto_exchange", "payment_service"],
            [s["action_details"]["transfer_source"] for s in incoming],
        ),
        (
            "sender",
            [
                "regular_sender",
                "anonymous_new_account",
                "anonymous_established_account",
            ],
            [s["action_details"]["sender_relationship"] for s in incoming],
        ),
        (
            "recipient",
            ["known_counterparty", "new_counterparty", "anonymous_wallet"],
            [s["context"]["recipient_type"] for s in transfers],
        ),
        (
            "velocity",
            ["spaced", "normal", "rapid"],
            [c["velocity"] for c in contexts if "velocity" in c],
        ),
        (
            "time",
            ["day", "evening", "night"],
            [c["time_of_day"] for c in contexts if "time_of_day" in c],
        ),
        (
            "channel",
            ["bank", "mobile", "web", "branch", "atm"],
            [c["channel"] for c in contexts if "channel" in c],
        ),
    ]:
        counts = Counter(observed)
        for value in values:
            features[f"{name}_{value}_count"] = counts[value]
            features[f"{name}_{value}_ratio"] = counts[value] / max(len(observed), 1)
    for left in sorted(
        set(["salary", "incoming_transfer", "card_transfer", "cash_withdrawal"])
    ):
        for right in [
            "salary",
            "incoming_transfer",
            "card_transfer",
            "cash_withdrawal",
        ]:
            features[f"transition_{left}_{right}"] = sum(
                a == left and b == right for a, b in zip(codes, codes[1:])
            )
    return features
