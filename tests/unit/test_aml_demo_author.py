"""Pre-training demo cases obey shared-context and causal-evidence contracts."""

import importlib
import importlib.util
from copy import deepcopy
import pytest


def module():
    name = "scripts.aml_dataset.aml_demo_author"
    assert importlib.util.find_spec(name), "independent shared-round author missing"
    return importlib.import_module(name)


def test_real_roster_and_financial_engine_accept_all_25_shared_context_cases():
    m = module()
    book, dossiers = m.author_casebook()
    from scripts.aml_demo_casebook import validate_roster
    from scripts.aml_dataset.aml_training import validate_sources
    from scripts.aml_dataset.aml_casebook import protocol

    rows = validate_roster(book)
    assert len(rows) == 25
    assert len(validate_sources(rows, protocol())) == 25
    assert sum(r["aml_label"] == 0 for r in rows) == 10
    assert sum(r["aml_label"] == 1 for r in rows) == 10
    assert sum(r["aml_label"] is None for r in rows) == 5
    for game, dossier in zip(book["rounds"], dossiers):
        configs = [c["record"]["public_snapshot"]["config"] for c in game["cases"]]
        assert all(c == configs[0] for c in configs)
        for case in game["cases"]:
            m.validate_case(dossier, case["record"])




@pytest.mark.parametrize(
    "change",
    ["history", "double_use", "future", "claim", "taint", "remaining", "label"],
)
def test_false_ledger_or_observation_rejected(change):
    m = module()
    book, dossiers = m.author_casebook()
    dossier = deepcopy(dossiers[0])
    row = deepcopy(book["rounds"][0]["cases"][2]["record"])
    if change == "history":
        dossier["history"][0]["amount"] = "1.00"
    elif change == "double_use":
        row["author_truth"]["actual_payments"][0]["amount"] = "800000.00"
    elif change == "future":
        row["economic_records"][0]["evidence"]["confirms"] = "completed_payment"
    elif change == "claim":
        row["public_snapshot"]["steps"][0]["claim_id"] = "opening"
    elif change == "taint":
        row["author_truth"]["criminal_episode"]["routing"][0]["criminal_amount"] = (
            "800000.00"
        )
    elif change == "remaining":
        row["author_truth"]["remaining_obligations"][2]["outstanding"] = "0.00"
    else:
        row["aml_label"] = 0
    with pytest.raises(ValueError):
        m.validate_case(dossier, row)


def test_scoped_evidence_does_not_make_all_shared_round_cases_equal():
    m = module()
    book, _ = m.author_casebook()
    from scripts.aml_dataset.aml_training import validate_sources
    from scripts.aml_dataset.aml_casebook import protocol

    rows = [c["record"] for g in book["rounds"] for c in g["cases"]]
    features = validate_sources(rows, protocol())
    for game in book["rounds"]:
        vectors = [features[c["record"]["scenario_id"]] for c in game["cases"]]
        assert len({str(v) for v in vectors}) >= 3
        high = game["cases"][2]["record"]
        assert any(
            p["operation"] == "salary" and p["settles_obligation"]
            for p in high["author_truth"]["actual_payments"]
        )
        assert any(
            p["operation"] == "purchase" and p["settles_obligation"]
            for p in high["author_truth"]["actual_payments"]
        )


def test_complete_development_closure_has_no_demo_links(tmp_path):
    m = module()
    report = m.build_demo(tmp_path / "demo")
    assert report["demo_records"] == 25
    assert report["cross_development_components"] == []
    assert 1 <= report["demo_components"] <= 5
    assert len(report["development_hashes"]) == 4
    assert report["reviewed_rows"] == 0 and report["release_ready"] is False
    with pytest.raises(FileExistsError):
        m.build_demo(tmp_path / "demo")


@pytest.mark.parametrize(
    "change",
    [
        "history_direction",
        "borrower",
        "future_utc",
        "authority",
        "control",
        "predicate",
        "refundable_balance",
    ],
)
def test_authority_and_economic_cause_are_validated_before_projection(change):
    m = module()
    book, dossiers = m.author_casebook()
    dossier = deepcopy(dossiers[4] if change == "borrower" else dossiers[0])
    if change == "history_direction":
        dossier["history"][0]["operation_code"] = "card_transfer"
    elif change == "borrower":
        e = next(e for e in dossier["events"] if e["kind"] == "member_loan_disbursed")
        e["beneficiary"] = dossier["obligations"][3]["creditor"]
        next(h for h in dossier["history"] if h["origin_event_id"] == e["id"])[
            "counterparty_id"
        ] = e["beneficiary"]
    elif change == "refundable_balance":
        e = next(
            e for e in dossier["events"] if e["kind"] == "nonrefundable_completed_work"
        )
        e["amount"] = "1.00"
    elif change == "predicate":
        next(
            e
            for e in dossier["events"]
            if e["kind"] == "intentional_escrow_embezzlement"
        )["kind"] = "lawful_gift"
    elif change == "future_utc":
        dossier["strategies"][2]["authority_records"][0]["checked_at"] = (
            "2026-09-13T08:30:00+00:00"
        )
    elif change == "authority":
        dossier["strategies"][2]["authority_records"][0]["source_event"] = (
            "invented-signature"
        )
    else:
        dossier["strategies"][2]["account_control"] = []
    with pytest.raises(ValueError):
        m._compile(dossier)


def test_lawful_source_custody_is_bound_to_actual_original_funds():
    m = module()
    book, dossiers = m.author_casebook()
    world = dossiers[0]
    low = book["rounds"][0]["cases"][0]["record"]
    receipt = next(
        p
        for p in low["author_truth"]["actual_payments"]
        if p["operation"] == "incoming_transfer"
    )
    funds = receipt["lawful_source"]
    assert (
        funds["owner"] == receipt["payer"] == funds["controller"] == funds["custodian"]
    )
    event = next(e for e in world["events"] if e["id"] == funds["basis"])
    event["kind"] = "unexplained_third_party_cash"
    with pytest.raises(ValueError):
        m._compile(world)


@pytest.mark.parametrize(
    "change",
    [
        "lawful_beneficiary",
        "lawful_origin",
        "source_owner",
        "source_controller",
        "source_custodian",
        "source_origin",
        "source_amount",
        "duplicate_actual",
        "duplicate_control",
    ],
)
def test_actual_destination_source_and_rosters_cannot_diverge(change):
    m = module()
    d = deepcopy(m.author_casebook()[1][0])
    lawful = d["strategies"][0]
    high = d["strategies"][2]
    if change.startswith("lawful") or change == "duplicate_actual":
        a = next(
            a for a in lawful["actual_payments"] if a["operation"] == "card_transfer"
        )
        if change == "lawful_beneficiary":
            a["actual_beneficiary"] = high["episode"]["collector"]
        elif change == "lawful_origin":
            a["actual_origin_event"] = "invented-origin"
        else:
            lawful["actual_payments"].append(deepcopy(a))
            a["amount"] = "800000.00"
    elif change == "duplicate_control":
        high["account_control"].append(deepcopy(high["account_control"][0]))
    else:
        a = next(
            a
            for a in high["actual_payments"]
            if a["id"] == high["episode"]["source_payment"]
        )
        field = {
            "source_origin": "actual_origin_event",
            "source_amount": "criminal_amount",
        }.get(change, change)
        a[field] = (
            "invented-origin"
            if change == "source_origin"
            else "1.00"
            if change == "source_amount"
            else "player"
        )
    with pytest.raises(ValueError):
        m._compile(d)


def test_development_inputs_are_captured_once_for_parsing_and_hashing(
    tmp_path, monkeypatch
):
    m = module()
    from pathlib import Path
    from collections import Counter

    reads = Counter()
    original = Path.read_bytes

    def read_bytes(path):
        if path.name == "casebook.jsonl" and "resources" in path.parts:
            reads[str(path)] += 1
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    m.build_demo(tmp_path / "single-snapshot")
    assert len(reads) == 5
    assert set(reads.values()) == {1}
