"""Hand-authored context fixtures, independent of evidence resolution."""

from copy import deepcopy

from scripts.check_expanded_balance import demo_config, demo_steps
from src.aml_workshop_simulator.services.semantic_contract import new_config


def context_fixture():
    old = demo_config()
    config = new_config(old)
    config["schema_version"] = 10
    steps = demo_steps(old)
    for step in steps:
        step["purpose_code"] = "shared_expense"
        step["claim_id"] = "shared"
        if step["card"]["code"] == "incoming_transfer":
            step["action_details"] = {"incoming_kind": "bank_transfer", "bank_country": "RU"}
    config["behavior"]["aml_context"] = {
        "version": "aml-context-v1",
        "as_of": "2026-09-13T09:00:00+03:00",
        "expected_activity": {
            "period_start": "2026-09-13T00:00:00+03:00",
            "period_end": "2026-09-14T00:00:00+03:00",
            "activity_kinds": ["shared_expense"],
            "expected_credit_min": "200000.00",
            "expected_credit_max": "250000.00",
            "expected_debit_min": "390000.00",
            "expected_debit_max": "420000.00",
        },
        "history_coverage": "complete",
        "history_start": "2026-08-14T09:00:00+03:00",
        "history_end": "2026-09-13T09:00:00+03:00",
        "opening_balance_facts": [],
        "purpose_catalog": [{"code": "shared_expense", "title": "Shared expense"},
                            {"code": "unknown", "title": "Unknown"}],
        "facts": [{
            "id": "shared", "fact_type": "payment_purpose",
            "verification_status": "verified", "provenance": "independent_record",
            "available_at": "2026-09-12T09:00:00+03:00",
            "valid_from": "2026-09-01T00:00:00+03:00",
            "valid_to": "2026-09-30T23:59:00+03:00",
            "counterparty_ids": ["A"],
            "operation_codes": ["incoming_transfer", "card_transfer"],
            "purpose_code": "shared_expense",
            "max_credit_amount": "100000.00", "max_debit_amount": "50000.00",
        }],
    }
    return deepcopy(config), deepcopy(steps)
