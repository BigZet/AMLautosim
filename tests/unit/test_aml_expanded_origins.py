"""Expansion must preserve truth, feasibility and conservative provenance closure."""

import importlib
import importlib.util
import hashlib
from pathlib import Path
from decimal import Decimal


def module():
    name = "scripts.aml_dataset.aml_expanded_origins"
    assert importlib.util.find_spec(name), "expanded economic-world author is missing"
    return importlib.import_module(name)


def test_new_families_have_causal_worlds_and_both_outcomes():
    m = module()
    roots = m.author_roots()
    assert {r["family_id"] for r in roots} == {"P05", "P07", "P08", "P09", "P10"}
    for root in roots:
        assert root["economic_narrative"]["ownership"]
        assert root["economic_narrative"]["obligation"]
        rows = m.compile_root(root)
        assert {r["aml_label"] for r in rows} == {0, 1, None}
        opaque = [
            r
            for r in rows
            if r["variant_recipe"] == "schedule-0-unavailable"
            and r["aml_label"] is not None
        ]
        assert opaque[0]["public_snapshot"] == opaque[1]["public_snapshot"]
        assert all(r["review"] is None for r in rows)


def test_full_engine_validation_and_closure_are_reported(tmp_path):
    m = module()
    report = m.build_origins(tmp_path / "draft")
    assert report["confirmed_candidate_rows"] == 150
    assert report["class_counts"] == {"0": 75, "1": 75}
    assert report["unresolved_rows"] == 6
    assert 0 < report["post_closure_components"] <= 6
    assert report["contradictory_feature_clusters"] > 0
    assert report["reviewed_rows"] == 0
    assert report["release_ready"] is False


def test_channel_and_dormant_history_are_actual_observations():
    m = module()
    for root in m.author_roots():
        public = m.compile_root(root)[0]["public_snapshot"]
        incoming = [
            s for s in public["steps"] if s["card"]["code"] == "incoming_transfer"
        ]
        if root["family_id"] == "P08":
            assert all(
                s["action_details"]["incoming_kind"] == "crypto_p2p" for s in incoming
            )
        if root["family_id"] == "P07":
            assert all(s["action_details"]["bank_country"] == "KG" for s in incoming)
        if root["family_id"] == "P09":
            assert public["config"]["behavior"]["history"]["operations"] == []
            assert (
                public["config"]["behavior"]["aml_context"]["history_coverage"]
                == "complete"
            )


def test_owned_crypto_and_refund_have_actual_acquisition_or_advance_traces():
    roots = {r["family_id"]: r for r in module().author_roots()}
    crypto = roots["P08"]["ledger"]
    assert len(crypto["historical_payments"]) == 3
    events = {e["id"]: e for e in crypto["events"]}
    for h in crypto["historical_payments"]:
        assert events[h["origin_event_id"]]["kind"] == "owned_wallet_lot_acquired"
        assert h["counterparty_id"] == "acquisition-seller"
    mixed = roots["P10"]["ledger"]
    advance = next(
        h
        for h in mixed["historical_payments"]
        if h["origin_event_id"] == "entitlement-3"
    )
    assert advance["amount"] == "80000.00"
    assert advance["counterparty_id"] == "funding-3"


def test_p05_cash_handover_routes_actual_proceeds_after_receipt():
    for root in module().author_roots():
        if root["family_id"] != "P05":
            continue
        for row in module().compile_root(root):
            cash = next(
                p for p in row["author_truth"]["actual_payments"] if p["id"] == "cash"
            )
            if row["aml_label"] == 0:
                assert cash["beneficiary"] == "cash-vendor"
                assert cash.get("settles_obligation", True)
            if row["aml_label"] != 1:
                continue
            assert cash["beneficiary"] == "collector"
            assert cash["settles_obligation"] is False
            episode = row["author_truth"]["criminal_episode"]
            allocations = {
                p["payment"]: Decimal(p["criminal_amount"])
                for p in episode["routing_allocations"]
            }
            assert allocations["cash"] == Decimal("10000")
            assert "cash" not in episode["continuing_lawful_payments"]
            balance = Decimal(0)
            for record in row["economic_records"]:
                if record["id"] in {"in-2", "in-3"}:
                    balance += Decimal(record["amount"])
                balance -= allocations.get(record["id"], Decimal(0))
                assert balance >= 0
            assert balance == 0


def test_p10_has_bound_lawful_salary_and_current_purchase_in_both_classes():
    root = next(r for r in module().author_roots() if r["family_id"] == "P10")
    for row in module().compile_root(root):
        codes = [s["card"]["code"] for s in row["public_snapshot"]["steps"]]
        assert "salary" in codes and "purchase" in codes
        assert len(codes) == 11
        records = {r["id"]: r for r in row["economic_records"]}
        for identity in ("background-salary", "background-purchase"):
            payment = records[identity]["actual_payment"]
            assert payment["obligation_id"]
            assert payment.get("settles_obligation", True)
            assert not payment.get("criminal_proceeds")
        if row["aml_label"] == 1:
            assert (
                row["author_truth"]["criminal_episode"]["criminal_amount"]
                == "160000.00"
            )


def test_source_hashes_bind_author_and_reused_compiler_file_bytes(tmp_path):
    m = module()
    report = m.build_origins(tmp_path / "checksums")
    for name in ("aml_expanded_origins.py", "aml_origins.py"):
        path = Path(m.__file__).with_name(name)
        assert (
            report["source_hashes"]["scripts/aml_dataset/" + name]
            == hashlib.sha256(path.read_bytes()).hexdigest()
        )
