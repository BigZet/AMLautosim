"""Observable v8 features shared by offline generation and future inference."""

from collections import Counter
from statistics import mean, pstdev
from zoneinfo import ZoneInfo
from .aml_episodes import flow_episodes, episode_features
from src.aml_workshop_simulator.services.expanded_simulation import (
    evaluate_expanded_scenario,
)

from src.aml_workshop_simulator.domain.operation_timeline import operation_timeline
from src.aml_workshop_simulator.services.counterparties import (
    canonical_expanded_steps,
    behavior_for,
)

FEATURE_VERSION = "aml-observable-v2.6"
CATEGORICAL_FEATURES = ["income_basis"]
CODES = ("salary", "incoming_transfer", "card_transfer", "cash_withdrawal", "purchase")
SOURCES = ("domestic_bank", "foreign_bank_kg", "payment_service", "crypto_exchange")


def extract_features(steps, config):
    steps = canonical_expanded_steps(steps, config)
    if not steps:
        raise ValueError("Nonempty chain required")
    behavior = behavior_for(config)
    parties = {p.id: p for p in behavior.counterparties}
    timeline = operation_timeline(steps, config["behavior"]["timeline"])
    amounts = [float(s["amount"]) for s in steps]
    codes = [s["card"]["code"] for s in steps]
    credits = [i for i, c in enumerate(codes) if c in ("salary", "incoming_transfer")]
    debits = [
        i for i, c in enumerate(codes) if c in ("card_transfer", "cash_withdrawal")
    ]
    inflow = sum(amounts[i] for i in credits)
    outflow = sum(amounts[i] for i in debits)
    history = behavior.history.operations
    observed = history is not None
    historical = {e.counterparty_id for e in history or [] if e.counterparty_id}
    recipients = [
        s["recipient_id"] for s in steps if s["card"]["code"] == "card_transfer"
    ]
    identified = [s.get("sender_id") or s.get("recipient_id") for s in steps]
    linked = [identity for identity in identified if identity]
    transfer_parties = [
        identified[i]
        for i, c in enumerate(codes)
        if c in ("incoming_transfer", "card_transfer")
    ]
    snapshot = evaluate_expanded_scenario(steps, config)
    totals = Counter()
    for i in debits:
        if identified[i]:
            totals[identified[i]] += amounts[i]
    hhi = sum((amount / max(outflow, 1)) ** 2 for amount in totals.values())
    financial = [i for i, c in enumerate(codes) if c != "purchase"]
    gaps = []
    cash_links = returns = 0
    seen_senders = set()
    longest = run = 0
    for i in financial:
        if i in credits:
            seen_senders.add(identified[i])
            run = 0
        else:
            returns += int(identified[i] is not None and identified[i] in seen_senders)
            run += 1
            longest = max(longest, run)
    for previous, current in zip(financial, financial[1:]):
        if previous in credits and current in debits:
            gaps.append(
                timeline[current]["elapsed_minutes"]
                - timeline[previous]["elapsed_minutes"]
            )
            cash_links += int(codes[current] == "cash_withdrawal")
    intervals = [r["interval_minutes"] for r in timeline[1:]]
    history_debits = [
        float(e.amount)
        for e in history or []
        if e.operation_code in ("card_transfer", "cash_withdrawal")
    ]
    features = {
        "num_steps": len(steps),
        "total_inflow": inflow,
        "fees": float(snapshot["totals"]["fees"]),
        "gross_outflow": float(snapshot["totals"]["gross_outflow"]),
        "target_outflow": outflow,
        "purchase_total": sum(a for a, c in zip(amounts, codes) if c == "purchase"),
        "amount_std": pstdev(amounts),
        "amount_mean": mean(amounts),
        "outflow_available_ratio": outflow
        / max(float(config["resources"]["initial_balance"]) + inflow, 1),
        "cash_share": sum(amounts[i] for i in debits if codes[i] == "cash_withdrawal")
        / max(outflow, 1),
        "recipient_hhi": hhi,
        "unique_recipients": len(set(recipients)),
        "return_to_sender_count": returns,
        "max_financial_debit_run": longest,
        "repeated_debit_share": (len(debits) - len({amounts[i] for i in debits}))
        / max(len(debits), 1),
        "elapsed_minutes": timeline[-1]["elapsed_minutes"],
        "interval_mean": mean(intervals) if intervals else 0,
        "interval_max": max(intervals, default=0),
        "credit_debit_links": len(gaps),
        "credit_cash_links": cash_links,
        "credit_debit_gap_mean": mean(gaps) if gaps else 0,
        # Bound each observed gap before averaging: one long wait cannot
        # substitute for waiting on the other credit-to-debit transitions.
        "credit_debit_gap_10_60_excess_mean": (
            mean(min(50, max(0, gap - 10)) for gap in gaps) if gaps else 0
        ),
        "fast_credit_debit_share": sum(g <= 10 for g in gaps) / max(len(gaps), 1),
        "night_share": sum(r["time_of_day"] == "night" for r in timeline) / len(steps),
        "limited_information_share": sum(
            parties[p].information_status != "sufficient" for p in transfer_parties
        )
        / max(len(transfer_parties), 1),
        "history_known": int(observed),
        "history_count": len(history or []),
        "history_empty": int(observed and not history),
        "history_debit_mean": mean(history_debits) if history_debits else 0,
        "history_has_debits": int(bool(history_debits)),
        "debit_mean_history_ratio": mean([amounts[i] for i in debits])
        / mean(history_debits)
        if history_debits and debits
        else 0,
        "unobserved_recipient_share": sum(p not in historical for p in recipients)
        / max(len(recipients), 1)
        if observed
        else 0,
        "income_basis": next(
            (
                s["action_details"].get("income_basis", "unknown")
                for s in steps
                if s["card"]["code"] == "salary"
            ),
            "absent",
        ),
    }
    for code in CODES:
        features[f"count_{code}"] = codes.count(code)
        for other in CODES:
            features[f"transition_{code}_{other}"] = sum(
                a == code and b == other for a, b in zip(codes, codes[1:])
            )
    for source in SOURCES:
        features[f"source_{source}_count"] = sum(
            s["action_details"].get("transfer_source") == source for s in steps
        )
    for kind in ("person", "institution", "merchant"):
        features[f"party_{kind}_share"] = sum(
            parties[p].kind == kind for p in linked
        ) / max(len(linked), 1)
    for status in ("sufficient", "limited", "unknown"):
        features[f"party_information_{status}_share"] = sum(
            parties[p].information_status == status for p in transfer_parties
        ) / max(len(transfer_parties), 1)
    features["known_relationship_share"] = sum(
        parties[p].personal_relationship == "known" for p in transfer_parties
    ) / max(len(transfer_parties), 1)
    for channel in ("mobile", "web", "branch", "atm"):
        features[f"channel_{channel}_count"] = sum(
            s["context"].get("channel") == channel for s in steps
        )
    for interval in (1, 10, 60, 1440):
        features[f"interval_{interval}_count"] = intervals.count(interval)
    for code in CODES:
        events = [e for e in history or [] if e.operation_code == code]
        features[f"history_{code}_count"] = len(events)
        features[f"history_{code}_amount"] = sum(float(e.amount) for e in events)
    historical_recipients = {
        e.counterparty_id for e in history or [] if e.operation_code == "card_transfer"
    }
    features["historical_recipient_overlap_share"] = sum(
        p in historical_recipients for p in recipients
    ) / max(len(recipients), 1)
    transfer_indices = [
        i for i, c in enumerate(codes) if c in ("incoming_transfer", "card_transfer")
    ]
    limited_amount = sum(
        amounts[i]
        for i in transfer_indices
        if parties[identified[i]].information_status != "sufficient"
    )
    features["limited_information_total_amount"] = limited_amount
    features["limited_information_amount_share"] = limited_amount / max(
        sum(amounts[i] for i in transfer_indices), 1
    )
    historical_amounts = {}
    historical_days = {}
    history_zone = ZoneInfo(config["behavior"]["timeline"]["timezone"])
    for event in history or []:
        if event.operation_code == "card_transfer":
            historical_amounts.setdefault(event.counterparty_id, []).append(float(event.amount))
            historical_days.setdefault(event.counterparty_id, set()).add(
                event.occurred_at.astimezone(history_zone).date()
            )
    comparable = 0
    transfer_count = 0
    for i, code in enumerate(codes):
        if code == "card_transfer":
            transfer_count += 1
            previous = historical_amounts.get(identified[i], [])
            if (len(historical_days.get(identified[i], set())) >= 2
                and max(previous) <= min(previous) * 2
                and mean(previous) * .5 <= amounts[i] <= mean(previous) * 2):
                comparable += 1
    features["comparable_historical_recipient_share"] = comparable / max(transfer_count, 1)
    features.update(episode_features(flow_episodes(steps, timeline)))
    # Observable sequence with one-minute gaps is the reference for the global
    # temporal ceiling, including changes in episode membership across midnight.
    reference = episode_features(flow_episodes(
        steps, [dict(elapsed_minutes=i) for i in range(len(steps))]
    ))
    features.update({"pace_reference_" + key: value for key, value in reference.items()})
    background_days = {
        event.occurred_at.astimezone(history_zone).date()
        for event in history or [] if event.operation_code in ("salary", "purchase")
    }
    features["history_stable_background"] = int(len(background_days) >= 2)
    return features
