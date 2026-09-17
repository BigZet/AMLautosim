"""Economic origin compilation tests: no label/review/independence shortcuts."""

from collections import Counter
from copy import deepcopy
import importlib
import importlib.util
import json

import pytest


def origins():
    name = "scripts.aml_dataset.aml_origins"
    assert importlib.util.find_spec(name) is not None, (
        "economic origin compiler is missing"
    )
    return importlib.import_module(name)


def test_authors_ledger_before_compilation_and_refuses_unknown_roots():
    module = origins()
    roots = module.author_roots()
    assert len(roots) == 10
    assert len({json.dumps(r["ledger"], sort_keys=True) for r in roots}) == 10
    for root in roots:
        assert root["review_status"] == "authored_unreviewed"
        assert root["template_ancestry"]
        assert root["ledger"]["opening_balance"] == "180000.00"
        assert root["ledger"]["participants"]
        obligations = {o["id"]: o for o in root["ledger"]["obligations"]}
        for payment in root["ledger"]["payments"]:
            assert payment["obligation_id"] in obligations
            assert payment["origin_event_id"]
            assert payment["amount"]
    bad = deepcopy(roots[0])
    bad["ledger"]["payments"][0]["obligation_id"] = "invented"
    with pytest.raises(ValueError, match="obligation"):
        module.compile_root(bad)


def test_compiled_variants_preserve_engine_contract_and_private_truth():
    module = origins()
    from scripts.aml_dataset.aml_casebook import protocol
    from scripts.aml_dataset.aml_training import validate_sources

    roots = module.author_roots()
    rows = [row for root in roots for row in module.compile_root(root)]
    features = validate_sources(rows, protocol())
    assert len(features) == 260
    assert Counter(r["aml_label"] for r in rows) == {0: 125, 1: 125, None: 10}
    assert all(
        r["review_status"] == "authored_unreviewed" and r["review"] is None
        for r in rows
    )
    assert all(len(r["public_snapshot"]["steps"]) <= 14 for r in rows)
    assert all(r["economic_records"] for r in rows)
    for root in roots:
        children = [r for r in rows if r["provenance"]["root_id"] == root["root_id"]]
        opaque = [
            r
            for r in children
            if r["variant_recipe"] == "schedule-0-unavailable"
            and r["label_status"] == "confirmed"
        ]
        assert len(opaque) == 2
        assert opaque[0]["public_snapshot"] == opaque[1]["public_snapshot"]
        criminal = next(r for r in children if r["aml_label"] == 1)
        assert (
            criminal["author_truth"]["criminal_episode"]["criminal_amount"]
            == "160000.00"
        )
        assert criminal["author_truth"]["criminal_episode"]["predicate_offence"]
        assert criminal["author_truth"]["criminal_episode"]["routing_allocations"]
        assert criminal["author_truth"]["lawful_receipts"]


def test_report_counts_closure_not_dossiers_and_never_promotes_review(tmp_path):
    module = origins()
    result = module.build_origins(tmp_path / "draft")
    assert result["release_ready"] is False
    assert result["reviewed_rows"] == 0
    assert result["authored_roots"] == 10
    assert result["confirmed_candidate_rows"] == 250
    assert result["post_closure_components"] <= 10
    assert result["minimum_components_required"] == 1200
    assert result["component_sizes"]
    assert result["challenge_freeze_status"] == "not_frozen_not_held_out"
    assert (tmp_path / "draft" / "roots.jsonl").exists()
    with pytest.raises(FileExistsError):
        module.build_origins(tmp_path / "draft")


def test_criminal_routing_cannot_spend_proceeds_before_receipt():
    from decimal import Decimal

    module = origins()
    for row in module.compile_root(module.author_roots()[0]):
        if row["aml_label"] != 1:
            continue
        allocations = {
            p["payment"]: Decimal(p["criminal_amount"])
            for p in row["author_truth"]["criminal_episode"]["routing_allocations"]
        }
        available = Decimal(0)
        for record in row["economic_records"]:
            if record["id"] in {"in-2", "in-3"}:
                available += Decimal(record["amount"])
            amount = allocations.get(record["id"], Decimal(0))
            assert amount <= available, "criminal proceeds routed before their receipt"
            available -= amount
        assert available == 0


def test_alternating_extra_is_a_distinct_observation_not_a_copied_row():
    module = origins()
    from scripts.aml_dataset.aml_provenance import digest

    for root in module.author_roots():
        rows = [
            r for r in module.compile_root(root) if r["label_status"] == "confirmed"
        ]
        keys = [(r["aml_label"], digest(r["public_snapshot"])) for r in rows]
        assert len(keys) == len(set(keys)), (
            "extra variant repeats the same labelled observation"
        )


def test_duplicate_return_has_two_original_payments_and_new_loan_has_future_liability():
    module = origins()
    roots = {r["root_id"]: r for r in module.author_roots()}
    ledger = roots["supplier_duplicate"]["ledger"]
    supplier_payments = [
        e
        for e in ledger["historical_payments"]
        if e["operation_code"] == "card_transfer"
        and e["counterparty_id"] == "funding-1"
    ]
    assert len(supplier_payments) == 2
    future = roots["loan_consolidation"]["ledger"]["future_obligations"]
    assert future[0]["debtor"] == "player"
    assert future[0]["creditor"] == "funding-1"
    assert future[0]["principal"] == "240000.00"


@pytest.mark.parametrize("mutation", ["opening", "event_amount", "payment_amount"])
def test_compiler_rejects_ledger_amounts_disagreeing_with_authored_economics(mutation):
    module = origins()
    root = module.author_roots()[0]
    if mutation == "opening":
        root["ledger"]["opening_balance"] = "0.00"
    elif mutation == "event_amount":
        root["ledger"]["events"][0]["amount"] = "1.00"
    else:
        root["ledger"]["payments"][0]["amount"] = "1.00"
    with pytest.raises(ValueError):
        module.compile_root(root)


def test_actual_criminal_world_binds_victims_accounts_and_loan_principal():
    module = origins()
    for root in module.author_roots():
        assert "worlds" in root, "explicit lawful/criminal/unresolved worlds required"
        world = root["worlds"]["criminal"]
        participants = {p["id"] for p in world["participants"]}
        events = {e["id"]: e for e in world["events"]}
        for payment in world["payments"]:
            assert payment["origin_event_id"] in events
            assert payment["payer"] in participants
            assert payment["beneficiary"] in participants
        criminal = [p for p in world["payments"] if p.get("criminal_proceeds")]
        assert {p["id"] for p in criminal} == {"in-2", "in-3"}
        for receipt in criminal:
            assert receipt["source_owner"] in participants
            assert receipt["source_account_controller"] in participants
            assert events[receipt["origin_event_id"]]["depends_on"]
        if root["root_id"] == "loan_consolidation":
            assert world["future_obligations"][0]["principal"] == "80000.00"


def test_observation_projection_follows_record_findings_without_reading_label():
    module = origins()
    root = module.author_roots()[0]
    assert "worlds" in root
    check = root["worlds"]["criminal"]["record_checks"]["in-2"]
    check["availability"] = "unavailable"
    row = next(
        r
        for r in module.compile_root(root)
        if r["aml_label"] == 1 and r["variant_recipe"] == "schedule-0-records"
    )
    fact = next(
        f
        for f in row["public_snapshot"]["config"]["behavior"]["aml_context"]["facts"]
        if f["id"] == "claim-in-2"
    )
    assert fact["verification_status"] == "unverified"
    assert row["author_truth"]["aml_episode_present"] is True


def test_stolen_asset_world_distinguishes_harmed_owner_from_proceeds_buyer():
    module = origins()
    root = next(r for r in module.author_roots() if r["root_id"] == "asset_portfolio")
    world = root["worlds"]["criminal"]
    receipt = next(p for p in world["payments"] if p["id"] == "in-2")
    events = {e["id"]: e for e in world["events"]}
    custody = events[receipt["origin_event_id"]]
    assert custody["actor"] == "stolen-goods-buyer-2"
    sale = events[custody["depends_on"][0]]
    assert sale["kind"] == "sale_of_misappropriated_asset_to_buyer"
    assert sale["beneficiary"] == "stolen-goods-buyer-2"


def test_history_mutation_and_invalid_finding_cannot_become_verified():
    module = origins()
    root = next(r for r in module.author_roots() if r["root_id"] == "asset_portfolio")
    root["ledger"]["historical_payments"][0]["amount"] = "1.00"
    with pytest.raises(ValueError):
        module.compile_root(root)


@pytest.mark.parametrize("mutation", ["unknown", "future", "world_opening"])
def test_projection_respects_unknown_future_findings_and_actual_world_balance(mutation):
    module = origins()
    root = module.author_roots()[0]
    finding = root["worlds"]["lawful"]["record_checks"]["in-1"]
    if mutation == "world_opening":
        root["worlds"]["lawful"]["opening_balance"] = "0.00"
        with pytest.raises(ValueError, match="opening"):
            module.compile_root(root)
        return
    if mutation == "unknown":
        finding.update(outcome="unknown", evidence={})
    else:
        finding["checked_at"] = "2027-01-01T00:00:00+03:00"
    row = next(
        r
        for r in module.compile_root(root)
        if r["aml_label"] == 0 and r["variant_recipe"] == "schedule-0-records"
    )
    fact = next(
        f
        for f in row["public_snapshot"]["config"]["behavior"]["aml_context"]["facts"]
        if f["id"] == "claim-in-1"
    )
    if mutation == "unknown":
        assert fact["verification_status"] == "unknown"
    else:
        assert fact["available_at"] == finding["checked_at"]
        from src.aml_workshop_simulator.services.aml_context import resolve_evidence

        evidence = resolve_evidence(**row["public_snapshot"])
        assert evidence[0]["covered_credit_amount"] == "0.00"
    root = module.author_roots()[0]
    root["worlds"]["lawful"]["record_checks"]["in-1"]["outcome"] = "invented"
    with pytest.raises(ValueError, match="finding"):
        module.compile_root(root)
