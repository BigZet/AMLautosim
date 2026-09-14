"""Observable aggregates for model v2. No rubric, labels, or learned weights."""

from collections import Counter
from statistics import mean

from src.aml_workshop_simulator.services.aml_dataset_features_v2 import (
    extract_features as extract_v2,
)
from src.aml_workshop_simulator.services.counterparties import canonical_expanded_steps

FEATURE_VERSION = "aml-observable-v3.0"
CATEGORICAL_FEATURES = ["income_basis"]


def extract_features(steps, config):
    values = canonical_expanded_steps(steps, config)
    features = extract_v2(values, config)
    salaries = [s for s in values if s["card"]["code"] == "salary"]
    credits = [
        s for s in values if s["card"]["code"] in ("salary", "incoming_transfer")
    ]
    debits = [
        s for s in values if s["card"]["code"] in ("card_transfer", "cash_withdrawal")
    ]
    salary_total = sum(float(s["amount"]) for s in salaries)
    credit_total = sum(float(s["amount"]) for s in credits)
    debit_total = sum(float(s["amount"]) for s in debits)
    features.update(
        salary_present=int(bool(salaries)),
        salary_total=salary_total,
        salary_credit_share=salary_total / max(credit_total, 1),
        salary_debit_ratio=salary_total / max(debit_total, 1),
        nonsalary_credit_total=credit_total - salary_total,
        financial_credit_count=len(credits),
        financial_debit_count=len(debits),
        debit_credit_ratio=debit_total / max(credit_total, 1),
    )
    for basis in ("payroll_registry", "service_contract", "no_reference"):
        matching = [s for s in salaries if s["action_details"]["income_basis"] == basis]
        features[f"salary_{basis}_present"] = int(bool(matching))
        features[f"salary_{basis}_total"] = sum(float(s["amount"]) for s in matching)
    # Aggregates describe financial operations only, independent of purchases/salary
    # diluting a per-operation share. They carry no rubric thresholds or coefficients.
    catalog = {p["id"]: p for p in config["behavior"]["counterparties"]}
    transfers = [
        s for s in values if s["card"]["code"] in ("incoming_transfer", "card_transfer")
    ]
    transfer_total = sum(float(s["amount"]) for s in transfers)
    for status in ("sufficient", "limited", "unknown"):
        matching = [
            s
            for s in transfers
            if catalog[s.get("sender_id") or s.get("recipient_id")][
                "information_status"
            ]
            == status
        ]
        features[f"transfer_{status}_amount_share"] = sum(
            float(s["amount"]) for s in matching
        ) / max(transfer_total, 1)
        features[f"transfer_{status}_count"] = len(matching)
    recipients = Counter(
        s["recipient_id"] for s in debits if s["card"]["code"] == "card_transfer"
    )
    features["recipient_max_count_share"] = max(recipients.values(), default=0) / max(
        sum(recipients.values()), 1
    )
    features["financial_debit_mean"] = (
        mean(float(s["amount"]) for s in debits) if debits else 0
    )
    return features
