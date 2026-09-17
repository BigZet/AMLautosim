import json
from pathlib import Path
import pytest
from scripts.aml_dataset.aml_labels import validate_label
from scripts.check_aml_casebook import audit_casebook

ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "resources/aml_dataset/aml-v1/pilot/casebook.jsonl"
PROTOCOL = ROOT / "config/ml/aml-classifier-v1-protocol.json"

def test_unresolved_cannot_be_negative():
    with pytest.raises(ValueError, match="unresolved"):
        validate_label({"aml_label": 0, "label_status": "unresolved"})

@pytest.mark.parametrize("label", [True, False, "0", 2, -1, None])
def test_confirmed_requires_integer_binary(label):
    with pytest.raises(ValueError):
        validate_label({"aml_label": label, "label_status": "confirmed"})

def test_historical_pilot_retains_labels_but_retired_purposes_fail_current_contract():
    rows = [json.loads(line) for line in PILOT.read_text(encoding='utf8').splitlines()]
    assert len(rows) == 120
    assert all(row['review_status'] == 'authored_unreviewed' for row in rows)
    for label in (0, 1, None):
        assert sum(row['aml_label'] == label for row in rows) == 40
    report = audit_casebook(PILOT, PROTOCOL)
    assert report["case_count"] == 87
    rejected = [error for error in report['errors'] if 'line' in error]
    assert len(rejected) == 33
    assert all('Назначение' in error['error'] for error in rejected)
    assert report["release_eligible"] is False
    assert report["review_counts"] == {"authored_unreviewed": 87}

def test_resource_failure_detected(tmp_path):
    record = json.loads(PILOT.read_text(encoding="utf-8").splitlines()[0])
    record["public_snapshot"]["steps"][0]["amount"] = "999999999"
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(record), encoding="utf-8")
    assert audit_casebook(path, PROTOCOL)["errors"]

def test_review_requires_independent_evidence():
    record = json.loads(PILOT.read_text(encoding="utf-8").splitlines()[0])
    record["review_status"] = "reviewed"
    with pytest.raises(ValueError, match="review"):
        validate_label(record)

def test_public_snapshot_rejects_hidden_label(tmp_path):
    record = json.loads(PILOT.read_text(encoding="utf-8").splitlines()[0])
    record["public_snapshot"]["aml_label"] = 0
    path = tmp_path / "leak.jsonl"
    path.write_text(json.dumps(record), encoding="utf-8")
    assert any("forbidden" in str(e) for e in audit_casebook(path, PROTOCOL)["errors"])


def test_confirmed_collision_is_retained_with_common_origin():
    rows = [json.loads(line) for line in PILOT.read_text(encoding="utf-8").splitlines()]
    for family in [f"P{i:02}" for i in range(1, 11)]:
        pair = [r for r in rows if r["family_id"] == family and r["scenario_id"].startswith(f"{family}-4-") and r["label_status"] == "confirmed"]
        assert {r["aml_label"] for r in pair} == {0, 1}
        assert pair[0]["public_snapshot"] == pair[1]["public_snapshot"]
        assert pair[0]["provenance_group_id"] == pair[1]["provenance_group_id"]
        assert not any(r["observability"]["distinguishable"] for r in pair)

@pytest.mark.parametrize("reviewer,method", [("codex-casebook-author","human_domain_review"), ("independent","automated_validation")])
def test_author_or_automation_cannot_approve(reviewer, method):
    record = json.loads(PILOT.read_text(encoding="utf-8").splitlines()[0])
    record.update(review_status="reviewed", review=dict(reviewer=reviewer, method=method, date="2026-09-16", rationale="checked"))
    with pytest.raises(ValueError, match="review"):
        validate_label(record)


def test_review_rejects_invalid_date():
    record = json.loads(PILOT.read_text(encoding="utf-8").splitlines()[0])
    record.update(review_status="reviewed", review=dict(reviewer="independent", method="independent_domain_review", date="yesterday", rationale="checked"))
    with pytest.raises(ValueError, match="review"):
        validate_label(record)


@pytest.mark.parametrize("defect", ["unknown_counterparty", "reversed_scope"])
def test_audit_enforces_full_context_validation(tmp_path, defect):
    record = json.loads(PILOT.read_text(encoding="utf-8").splitlines()[0])
    fact = record["public_snapshot"]["config"]["behavior"]["aml_context"]["facts"][0]
    if defect == "unknown_counterparty":
        fact["counterparty_ids"] = ["nonexistent-party"]
    else:
        fact["valid_from"] = "2027-01-01T00:00:00+03:00"
    path = tmp_path / "invalid_context.jsonl"
    path.write_text(json.dumps(record), encoding="utf-8")
    errors = audit_casebook(path, PROTOCOL)["errors"]
    assert any(e.get("line") == 1 for e in errors)


def test_all_lawful_payment_claims_cover_intended_flows():
    from decimal import Decimal
    from src.aml_workshop_simulator.services.aml_context import resolve_evidence
    from src.aml_workshop_simulator.domain.operation_purposes import allowed_purposes
    for row in map(json.loads, PILOT.read_text(encoding="utf-8").splitlines()):
        public = row["public_snapshot"]
        assert all(s.get("claim_id") for s in public["steps"])
        if any(s['purpose_code'] not in allowed_purposes(s) for s in public['steps']):
            with pytest.raises(ValueError, match='Назначение'):
                resolve_evidence(public['steps'], public['config'])
            continue
        evidence = resolve_evidence(public["steps"], public["config"])
        assert not any(e["mismatch"] for e in evidence)
        if row["aml_label"] == 0 and row["observability"]["distinguishable"]:
            assert sum(Decimal(e["covered_credit_amount"]) for e in evidence) == Decimal("240000.00")
            assert Decimal(row["expected_evidence"]["verified_credit_amount"]) == Decimal("240000.00")
            assert sum(Decimal(e["covered_debit_amount"]) for e in evidence) == Decimal("400000.00")
            assert Decimal(row["expected_evidence"]["verified_debit_amount"]) == Decimal("400000.00")
        if row["aml_label"] == 1 and row["observability"]["distinguishable"]:
            assert [i for i,e in enumerate(evidence,1) if e["contradicted"]] == row["expected_evidence"]["contradicted_steps"]
            assert any(e["contradicted"] for e in evidence)

def test_sale_sources_cash_and_payouts_are_direction_scoped():
    for row in map(json.loads, PILOT.read_text(encoding="utf-8").splitlines()):
        public = row["public_snapshot"]
        facts = {f["id"]: f for f in public["config"]["behavior"]["aml_context"]["facts"]}
        for step in public["steps"]:
            fact = facts[step["claim_id"]]
            code = step["card"]["code"]
            if code == "cash_withdrawal":
                assert fact["counterparty_ids"] == []
            if row["family_id"] in {"P04", "P08"} and code == "card_transfer":
                assert step["purpose_code"] == "personal_spending"
                assert fact["fact_type"] == "payment_purpose"
                assert fact["max_credit_amount"] == "0.00"
            if row["family_id"] in {"P04", "P08"} and code == "incoming_transfer":
                assert fact["operation_codes"] == ["incoming_transfer"]
                assert fact["max_debit_amount"] == "0.00"

def test_reactivation_cases_have_complete_empty_history():
    for row in map(json.loads, PILOT.read_text(encoding="utf-8").splitlines()):
        if row["family_id"] == "P09":
            behavior = row["public_snapshot"]["config"]["behavior"]
            assert behavior["history"]["operations"] == []
            assert behavior["aml_context"]["history_coverage"] == "complete"

def test_salary_variants_use_actual_obligations():
    for row in map(json.loads, PILOT.read_text(encoding="utf-8").splitlines()):
        if row["family_id"] == "P10":
            variant = int(row["scenario_id"].split("-")[1]) - 1
            debit = next(s for s in row["public_snapshot"]["steps"] if s["card"]["code"] == "card_transfer")
            assert debit["purpose_code"] == ["shared_expense", "refund", "loan", "personal_spending"][variant]
            assert row["economic_records"]


@pytest.mark.parametrize("field,value", [("review", "not-an-object"), ("author_truth", "hidden"), ("observability", [True]), ("hypothesis_source", 2)])
def test_malformed_nested_records_return_validation_errors(tmp_path, field, value):
    row = json.loads(PILOT.read_text(encoding="utf-8").splitlines()[0])
    row[field] = value
    if field == "review":
        row["review_status"] = "reviewed"
    with pytest.raises(ValueError):
        validate_label(row)
    path = tmp_path / "malformed.jsonl"
    path.write_text(json.dumps(row), encoding="utf-8")
    assert any(e.get("line") == 1 for e in audit_casebook(path, PROTOCOL)["errors"])

@pytest.mark.parametrize("key", ["review", "rationale", "author_id", "label_protocol_version", "forbidden_information", "economic_records", "expected_evidence"])
def test_nested_authoring_metadata_never_public(key):
    from scripts.aml_dataset.aml_labels import validate_public
    with pytest.raises(ValueError, match="forbidden"):
        validate_public({"behavior":{"extra":{key: {"rationale":"approved AML case"}}}})


@pytest.mark.parametrize("variant,category,purpose", [
    ("P01-4", "family_event", "shared_expense"),
    ("P05-2", "used_household_goods", "personal_spending"),
    ("P05-4", "family_event_cash", "personal_spending"),
    ("P06-2", "recurring_shared_cost", "shared_expense"),
    ("P06-4", "personal_reimbursement", "shared_expense"),
    ("P07-2", "cross_border_shared_cost", "shared_expense"),
    ("P07-4", "foreign_relative_repayment", "loan"),
    ("P09-4", "reserve_account_family_settlement", "shared_expense"),
])
def test_variant_original_events_preserve_intended_obligations(variant, category, purpose):
    for row in map(json.loads, PILOT.read_text(encoding="utf-8").splitlines()):
        if row["scenario_id"].startswith(variant + "-"):
            for record, step in zip(row["economic_records"][1:], row["public_snapshot"]["steps"]):
                code = step["card"]["code"]
                affected = code == "cash_withdrawal" if variant.startswith("P05") else code in {"incoming_transfer", "card_transfer"}
                if affected:
                    assert step["purpose_code"] == purpose
                    assert record["event_details"]["category"] == category
                    assert record["event_details"]["original_record_id"]
                    assert record["event_details"]["relationship"]
                    assert record["amount"] in record["original_event"]


def test_vehicle_sale_is_one_owned_vehicle_three_instalments():
    for row in map(json.loads, PILOT.read_text(encoding="utf-8").splitlines()):
        if row["scenario_id"].startswith("P04-2-"):
            events = [r for r in row["economic_records"] if r.get("operation") == "incoming_transfer"]
            assert [e["event_details"]["instalment_number"] for e in events] == [1,2,3]
            assert {e["event_details"]["asset_id"] for e in events} == {"owned-vehicle-01"}
            assert {e["event_details"]["sale_total"] for e in events} == {"240000.00"}
            assert {e["amount"] for e in events} == {"80000.00"}
            if row["aml_label"] == 1:
                assert events[0]["observed_record_status"] == "verified"
                assert all(e["observed_record_status"] == "contradicted" for e in events[1:])
                assert row["author_truth"]["vehicle_sale_counterexample"]["lawful_sale_receipt"] == "80000.00"
