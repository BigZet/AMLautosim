"""Observable educational patterns, explicitly NOT a criminal-outcome label.

Thresholds are game teaching conventions, not regulatory thresholds or measured
fraud rates. Neither counterparties' reputation nor private narratives enter.
"""

from collections import Counter
from decimal import Decimal

POLICY = {
    "version": "aml-chain-pattern-v1",
    "target": "observable_educational_pattern",
    "meaning": "Probability of matching a taught transaction-chain pattern, not proof of criminal activity",
    "fast_minutes": 10,
    "matched_receipt_ratio_min": 0.85,
    "matched_receipt_ratio_max": 1.05,
    "small_payment_ratio_max": 0.70,
    "rules": {
        "repeated_matched_relay": "at least two rapid episodes with an individual debit matching 85–105% of the receipt",
        "repeated_fanout": "at least two rapid episodes paying two or more recipients, at least three recipients overall",
        "consolidation": "at least two rapid debit episodes, at least two senders, one recipient gets at least 80% of card outflow",
        "cash_conversion": "cash within 10 minutes of a receipt, at least two rapid debit episodes, cash is at least 15% of financial outflow",
        "repeated_returns": "at least two rapid episodes returning at least half the receipt to its sender",
        "repeated_fragmentation": "at least two rapid episodes with multiple payments each at most 70% of receipt, at least seven card payments and at least 70% share of repeated card amounts",
    },
    "negative_meaning": "No pattern from this finite teaching catalog matches; does not establish lawful funds",
    "label_source": "deterministic observable teaching policy; weak supervision, not expert criminal adjudication",
}


def chain_features(steps):
    times, now = [], 0
    for step in steps:
        now += step.get("interval_minutes") or 0
        times.append(now)
    credits = [
        i for i, s in enumerate(steps) if s["card"]["code"] == "incoming_transfer"
    ]
    recipients, amounts, senders = Counter(), Counter(), set()
    cash, financial, before = Decimal(0), Decimal(0), Decimal(0)
    counts = Counter()
    for i, step in enumerate(steps):
        code, amount = step["card"]["code"], Decimal(step["amount"])
        if code == "incoming_transfer":
            senders.add(step.get("sender_id"))
        if code in ("card_transfer", "cash_withdrawal"):
            financial += amount
            if not credits or i < credits[0]:
                before += amount
        if code == "cash_withdrawal":
            cash += amount
        if code == "card_transfer":
            recipients[step.get("recipient_id")] += amount
            amounts[amount] += 1
    for n, start in enumerate(credits):
        stop = credits[n + 1] if n + 1 < len(credits) else len(steps)
        receipt = Decimal(steps[start]["amount"])
        rapid = [
            s
            for i, s in enumerate(steps[start + 1 : stop], start + 1)
            if times[i] - times[start] <= POLICY["fast_minutes"]
            and s["card"]["code"] in ("card_transfer", "cash_withdrawal")
        ]
        cards = [s for s in rapid if s["card"]["code"] == "card_transfer"]
        counts["rapid"] += bool(rapid)
        counts["fanout"] += len({s.get("recipient_id") for s in cards}) >= 2
        counts["cash"] += any(s["card"]["code"] == "cash_withdrawal" for s in rapid)
        counts["matched"] += any(
            Decimal("0.85") * receipt
            <= Decimal(s["amount"])
            <= Decimal("1.05") * receipt
            for s in rapid
        )
        returned = sum(
            (
                Decimal(s["amount"])
                for s in cards
                if s.get("recipient_id") == steps[start].get("sender_id")
            ),
            Decimal(0),
        )
        counts["returned"] += returned >= receipt / 2
        counts["small_split"] += len(cards) >= 2 and all(
            Decimal(s["amount"]) <= Decimal("0.70") * receipt for s in cards
        )
    card_count = sum(amounts.values())
    return {
        "chain_rapid_episodes": counts["rapid"],
        "chain_matched_episodes": counts["matched"],
        "chain_fanout_episodes": counts["fanout"],
        "chain_cash_episodes": counts["cash"],
        "chain_return_episodes": counts["returned"],
        "chain_small_split_episodes": counts["small_split"],
        "chain_distinct_senders": len(senders),
        "chain_distinct_recipients": len(recipients),
        "chain_max_recipient_share": float(
            max(recipients.values(), default=0) / sum(recipients.values())
        )
        if recipients
        else 0.0,
        "chain_cash_share": float(cash / financial) if financial else 0.0,
        "chain_card_count": card_count,
        "chain_repeated_amount_share": sum(n for n in amounts.values() if n >= 2)
        / card_count
        if card_count
        else 0.0,
        "chain_precredit_outflow": float(before),
    }


def label_pattern(features):
    f = features
    rules = {
        "repeated_matched_relay": f["chain_matched_episodes"] >= 2,
        "repeated_fanout": f["chain_fanout_episodes"] >= 2
        and f["chain_distinct_recipients"] >= 3,
        "consolidation": f["chain_rapid_episodes"] >= 2
        and f["chain_distinct_senders"] >= 2
        and f["chain_max_recipient_share"] >= 0.8,
        "cash_conversion": f["chain_cash_episodes"] >= 1
        and f["chain_rapid_episodes"] >= 2
        and f["chain_cash_share"] >= 0.15,
        "repeated_returns": f["chain_return_episodes"] >= 2,
        "repeated_fragmentation": f["chain_small_split_episodes"] >= 2
        and f["chain_card_count"] >= 7
        and f["chain_repeated_amount_share"] >= 0.7,
    }
    matches = [name for name, matched in rules.items() if matched]
    return int(bool(matches)), matches
