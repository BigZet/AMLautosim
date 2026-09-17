"""V5 observable features for educational AML probability, not a rubric.

The inherited numerical allowlist is frozen here. Geography values, identifiers,
authored outcomes and reviewer metadata never become model inputs.
"""
from datetime import datetime
from decimal import Decimal
from collections import defaultdict

from src.aml_workshop_simulator.domain.operation_timeline import operation_timeline
from src.aml_workshop_simulator.schemas.aml_context import AMLContext
from src.aml_workshop_simulator.services.aml_context import (
    canonical_steps, semantic_config, semantic_steps, resolve_evidence, evaluate,
)
from src.aml_workshop_simulator.services.aml_dataset_features_v4 import extract_features as extract_v4
from src.aml_workshop_simulator.services.aml_episodes import flow_episodes

FEATURE_VERSION = "aml-observable-v5.0"
CATEGORICAL_FEATURES = ["income_basis"]
BASE_FEATURES = [
    "amount_mean",
    "amount_std",
    "cash_share",
    "channel_atm_count",
    "channel_branch_count",
    "channel_mobile_count",
    "channel_web_count",
    "comparable_historical_recipient_share",
    "count_card_transfer",
    "count_cash_withdrawal",
    "count_incoming_transfer",
    "count_purchase",
    "count_salary",
    "credit_cash_links",
    "credit_debit_gap_10_60_excess_mean",
    "credit_debit_gap_mean",
    "credit_debit_links",
    "elapsed_minutes",
    "fast_credit_debit_share",
    "fees",
    "gross_outflow",
    "has_recipient_transfers",
    "historical_recipient_overlap_share",
    "history_card_transfer_amount",
    "history_card_transfer_count",
    "history_count",
    "history_debit_mean",
    "history_empty",
    "history_has_debits",
    "history_incoming_bank_transfer_amount",
    "history_incoming_bank_transfer_count",
    "history_incoming_crypto_p2p_amount",
    "history_incoming_crypto_p2p_count",
    "history_incoming_exchange_withdrawal_amount",
    "history_incoming_exchange_withdrawal_count",
    "history_incoming_payment_service_amount",
    "history_incoming_payment_service_count",
    "history_incoming_transfer_amount",
    "history_incoming_transfer_count",
    "history_known",
    "history_purchase_amount",
    "history_purchase_count",
    "history_salary_amount",
    "history_salary_count",
    "history_stable_background",
    "income_basis",
    "incoming_bank_transfer_amount",
    "incoming_bank_transfer_count",
    "incoming_crypto_p2p_amount",
    "incoming_crypto_p2p_count",
    "incoming_exchange_withdrawal_amount",
    "incoming_exchange_withdrawal_count",
    "incoming_payment_service_amount",
    "incoming_payment_service_count",
    "interval_10_count",
    "interval_1440_count",
    "interval_1_count",
    "interval_60_count",
    "interval_max",
    "interval_mean",
    "known_relationship_share",
    "limited_information_amount_share",
    "limited_information_share",
    "limited_information_total_amount",
    "matched_large_episode_count",
    "matched_large_tempo_mean",
    "max_financial_debit_run",
    "night_share",
    "num_steps",
    "observed_return_cycle_count",
    "party_information_limited_share",
    "party_information_sufficient_share",
    "party_information_unknown_share",
    "party_institution_share",
    "party_merchant_share",
    "party_person_share",
    "purchase_total",
    "recipient_hhi",
    "relationship_applicable_share",
    "repeated_debit_share",
    "return_to_sender_count",
    "salary_total",
    "total_inflow",
    "transition_card_transfer_card_transfer",
    "transition_card_transfer_incoming_transfer",
    "transition_card_transfer_purchase",
    "transition_card_transfer_salary",
    "transition_cash_withdrawal_card_transfer",
    "transition_incoming_transfer_card_transfer",
    "transition_incoming_transfer_cash_withdrawal",
    "transition_incoming_transfer_incoming_transfer",
    "transition_incoming_transfer_purchase",
    "transition_purchase_card_transfer",
    "transition_purchase_incoming_transfer",
    "transition_purchase_purchase",
    "transition_salary_card_transfer",
    "unique_recipients",
    "unobserved_recipient_share"
]
CREDIT_CODES = {"salary", "incoming_transfer"}
CONTEXT_FEATURES = [
    name
    for direction in ("credit", "debit")
    for name in (
        f"explained_{direction}_amount", f"explanation_{direction}_applicable",
        f"explanation_{direction}_share", f"unknown_{direction}_share",
        f"unverified_{direction}_share", f"contradicted_{direction}_share",
        f"mismatched_{direction}_share",
    )
] + [
    "context_history_complete", "context_history_partial", "context_history_unknown",
    "observed_inactivity", "context_unknown_step_share", "purpose_unknown_share",
    "activity_purpose_mismatch_share", "expected_volume_comparable",
    "expected_credit_range_known", "expected_credit_excess_ratio",
    "expected_debit_range_known", "expected_debit_excess_ratio",
    "opening_balance_explanation_applicable", "opening_balance_explained_share",
    "balance_turnover_applicable", "ending_balance_turnover_ratio",
    "mean_balance_turnover_ratio",
    "historical_recipient_comparison_applicable",
    "card_transfer_history_comparable", "card_transfer_mean_history_ratio",
    "cash_withdrawal_history_comparable", "cash_withdrawal_mean_history_ratio",
    "activity_purpose_comparable_share",
    "expected_credit_excess_ratio_applicable", "expected_credit_excess_amount",
    "expected_debit_excess_ratio_applicable", "expected_debit_excess_amount",
    "observed_episode_count", "episode_recipient_concentration_applicable",
    "episode_sender_concentration_applicable", "episode_recipient_hhi_mean",
    "episode_sender_hhi_mean", "episode_fan_in_max", "episode_fan_out_max",
]
FEATURE_NAMES = BASE_FEATURES + CONTEXT_FEATURES


def extract_features(steps: list, config: dict) -> dict:
    canonical = canonical_steps(steps, config)
    inherited = extract_v4(semantic_steps(canonical), semantic_config(config))
    f = {name: inherited[name] for name in BASE_FEATURES}
    ctx = AMLContext.model_validate(config["behavior"]["aml_context"])
    evidence = resolve_evidence(canonical, config)
    moments = operation_timeline(canonical, config["behavior"]["timeline"])
    totals = {"credit": Decimal(0), "debit": Decimal(0)}
    explained = {"credit": Decimal(0), "debit": Decimal(0)}
    buckets = {name: {"credit": Decimal(0), "debit": Decimal(0)}
               for name in ("unknown", "unverified", "contradicted", "mismatched")}
    for step, row in zip(canonical, evidence):
        direction = "credit" if step["card"]["code"] in CREDIT_CODES else "debit"
        amount = Decimal(step["amount"])
        totals[direction] += amount
        explained[direction] += Decimal(row[f"covered_{direction}_amount"])
        for name in ("unknown", "contradicted"):
            if row[name]:
                buckets[name][direction] += amount
        if row["verification_status"] == "unverified" and row["applicable"]:
            buckets["unverified"][direction] += amount
        if row["mismatch"]:
            buckets["mismatched"][direction] += amount
    for direction in ("credit", "debit"):
        denominator = totals[direction]
        f[f"explained_{direction}_amount"] = float(explained[direction])
        f[f"explanation_{direction}_applicable"] = int(denominator > 0)
        f[f"explanation_{direction}_share"] = float(explained[direction] / denominator) if denominator else 0.0
        for name, values in buckets.items():
            f[f"{name}_{direction}_share"] = float(values[direction] / denominator) if denominator else 0.0
    for state in ("complete", "partial", "unknown"):
        f[f"context_history_{state}"] = int(ctx.history_coverage == state)
    history = config["behavior"]["history"]["operations"]
    complete_history = ctx.history_coverage == "complete"
    f["history_empty"] = int(complete_history and history == [])
    f["historical_recipient_comparison_applicable"] = int(complete_history and f["has_recipient_transfers"])
    if not complete_history:
        f["unobserved_recipient_share"] = 0.0
    # Compare per-operation amounts only within the same operation type.
    # Window totals are never compared to the artificial round turnover.
    for code in ("card_transfer", "cash_withdrawal"):
        previous = [Decimal(e["amount"]) for e in history or [] if e["operation_code"] == code]
        current = [Decimal(s["amount"]) for s in canonical if s["card"]["code"] == code]
        comparable_history = complete_history and bool(previous) and bool(current)
        f[f"{code}_history_comparable"] = int(comparable_history)
        f[f"{code}_mean_history_ratio"] = float(
            (sum(current) / len(current)) / (sum(previous) / len(previous))
        ) if comparable_history else 0.0
    f["observed_inactivity"] = int(ctx.history_coverage == "complete" and history == [])
    f["context_unknown_step_share"] = sum(r["unknown"] for r in evidence) / max(len(evidence), 1)
    f["purpose_unknown_share"] = sum(s["purpose_code"] == "unknown" for s in canonical) / max(len(canonical), 1)
    activity = ctx.expected_activity
    comparable_purposes = [
        s for s, moment in zip(canonical, moments)
        if activity.period_start <= datetime.fromisoformat(moment["occurred_at"]) <= activity.period_end
    ]
    f["activity_purpose_comparable_share"] = len(comparable_purposes) / max(len(canonical), 1)
    f["activity_purpose_mismatch_share"] = sum(
        s["purpose_code"] != "unknown" and s["purpose_code"] not in activity.activity_kinds
        for s in comparable_purposes
    ) / max(len(comparable_purposes), 1)
    start = datetime.fromisoformat(config["behavior"]["timeline"]["starts_at"])
    end = datetime.fromisoformat(moments[-1]["occurred_at"]) if moments else start
    comparable = bool(moments) and start == activity.period_start and end == activity.period_end
    f["expected_volume_comparable"] = int(comparable)
    for direction in ("credit", "debit"):
        maximum = getattr(activity, f"expected_{direction}_max")
        applicable = comparable and maximum is not None and maximum > 0
        f[f"expected_{direction}_range_known"] = int(maximum is not None)
        f[f"expected_{direction}_excess_ratio_applicable"] = int(applicable)
        f[f"expected_{direction}_excess_amount"] = (
            float(max(Decimal(0), totals[direction] - maximum))
            if comparable and maximum is not None else 0.0
        )
        f[f"expected_{direction}_excess_ratio"] = (
            float(max(Decimal(0), totals[direction] / maximum - 1)) if applicable else 0.0
        )
    initial = Decimal(config["resources"]["initial_balance"])
    cutoff = min(ctx.as_of, end)
    opening_ids = set(ctx.opening_balance_facts)
    covered_opening = sum(
        (min(fact.max_credit_amount, fact.max_debit_amount) for fact in ctx.facts
         if fact.id in opening_ids and fact.verification_status == "verified"
         and fact.available_at <= cutoff and fact.valid_from <= start <= fact.valid_to),
        Decimal(0),
    )
    f["opening_balance_explanation_applicable"] = int(initial > 0)
    f["opening_balance_explained_share"] = float(min(initial, covered_opening) / initial) if initial else 0.0
    result = evaluate(canonical, config)
    balances = [Decimal(row["resources_after"]["balance"]) for row in result["per_step"]]
    turnover = totals["debit"]
    f["balance_turnover_applicable"] = int(turnover > 0)
    f["ending_balance_turnover_ratio"] = float((balances[-1] if balances else initial) / turnover) if turnover else 0.0
    f["mean_balance_turnover_ratio"] = float(sum(balances, Decimal(0)) / len(balances) / turnover) if balances and turnover else 0.0
    episodes = flow_episodes(canonical, moments)
    f["observed_episode_count"] = len(episodes)
    for role, codes, count_name in (
        ("sender", CREDIT_CODES, "episode_fan_in_max"),
        ("recipient", {"card_transfer"}, "episode_fan_out_max"),
    ):
        concentrations, counts = [], []
        for episode in episodes:
            amounts = defaultdict(Decimal)
            for step, moment in zip(canonical, moments):
                if (step["card"]["code"] in codes and
                    episode["start"] <= moment["elapsed_minutes"] <= episode["end"]):
                    amounts[step[f"{role}_id"]] += Decimal(step["amount"])
            total = sum(amounts.values(), Decimal(0))
            if total:
                concentrations.append(float(sum((amount/total)**2 for amount in amounts.values())))
                counts.append(len(amounts))
        f[f"episode_{role}_concentration_applicable"] = int(bool(concentrations))
        f[f"episode_{role}_hhi_mean"] = sum(concentrations)/len(concentrations) if concentrations else 0.0
        f[count_name] = max(counts, default=0)
    return {name: f[name] for name in FEATURE_NAMES}
