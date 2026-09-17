"""Causal conservation failures must be rejected before publication."""

import importlib
import importlib.util
from dataclasses import replace
from copy import deepcopy
import pytest


def module():
    name = "scripts.aml_dataset.aml_world_graph"
    assert importlib.util.find_spec(name), "typed causal compiler missing"
    return importlib.import_module(name)


def test_pilot_has_causal_topologies_and_financially_valid_opaque_pairs():
    m = module()
    roots = m.author_roots()
    assert 50 <= len(roots) <= 100
    assert len({tuple(p.operation for p in r.payments) for r in roots}) >= 3
    rows = [row for root in roots for row in m.compile_root(root)]
    from scripts.aml_dataset.aml_training import validate_sources
    from scripts.aml_dataset.aml_casebook import protocol

    features = validate_sources(rows, protocol())
    assert len(features) == len(rows)
    for root in roots:
        pair = [
            r
            for r in m.compile_root(root)
            if r["variant_recipe"] == "opaque" and r["aml_label"] is not None
        ]
        assert pair[0]["public_snapshot"] == pair[1]["public_snapshot"]
        assert all(r["review"] is None for r in pair)


@pytest.mark.parametrize(
    "breakage", ["cycle", "double_use", "future", "party", "roster", "crime"]
)
def test_invalid_world_rejected(breakage):
    m = module()
    root = deepcopy(m.author_roots()[0])
    if breakage == "cycle":
        root.events[0] = replace(root.events[0], parents=(root.events[-1].id,))
    elif breakage == "double_use":
        root.payments.append(replace(root.payments[0], id="duplicate"))
    elif breakage == "future":
        root.observations[0] = replace(root.observations[0], confirms="settled")
    elif breakage == "party":
        root.payments[0] = replace(root.payments[0], payer="unsupported")
    elif breakage == "roster":
        root.observations.pop()
    else:
        root.crime["source_amount"] = 1
    with pytest.raises(ValueError):
        m.validate_world(root)


def test_partial_refund_and_repayment_are_bound_to_actual_history():
    m = module()
    for root in m.author_roots():
        m.validate_world(root)
        if root.source in {"refund", "debt"}:
            assert root.history
            assert any(
                e.kind == "paid_advance"
                if root.source == "refund"
                else e.kind == "loan_disbursement"
                for e in root.events
            )
            assert (
                sum(o.principal for o in root.obligations if o.creditor == "player")
                == 240000
            )


def test_consistency_validator_detects_record_and_snapshot_tampering():
    m = module()
    root = m.author_roots()[0]
    row = m.compile_root(root)[0]
    row["economic_records"][0]["amount"] = "1.00"
    with pytest.raises(ValueError):
        m.validate_record(root, row)
    row = m.compile_root(root)[0]
    row["public_snapshot"]["steps"][0]["amount"] = "1.00"
    with pytest.raises(ValueError):
        m.validate_record(root, row)


def test_lawful_world_can_refute_a_false_cover_without_becoming_criminal():
    m = module()
    rows = m.compile_root(m.author_roots()[0])
    lawful = [r for r in rows if r["aml_label"] == 0]
    assert any(
        any(
            f["verification_status"] == "contradicted"
            for f in r["public_snapshot"]["config"]["behavior"]["aml_context"]["facts"]
        )
        for r in lawful
    )
    for r in lawful:
        if r["variant_recipe"] == "wrong_cover":
            record = r["economic_records"][0]
            assert record["record_check"]["actual_purpose"] == "service_payment"
            assert (
                record["record_check"]["claimed_purpose"]
                != record["record_check"]["actual_purpose"]
            )
            assert record["actual_payment"]["settles_obligation"] is True


@pytest.mark.parametrize(
    "breakage", ["title", "agency", "history_party", "crime_channel", "crime_owner"]
)
def test_economic_role_and_custody_mismatches_rejected(breakage):
    m = module()
    source = (
        "asset" if breakage == "title" else "cost" if breakage == "agency" else "debt"
    )
    root = deepcopy(
        next(
            r
            for r in m.author_roots()
            if r.source == source
            and any(p.operation == "cash_withdrawal" for p in r.payments)
        )
    )
    if breakage == "title":
        root.rights[0]["owner"] = "source-0"
    elif breakage == "agency":
        root.rights[0]["principal"] = "player"
    elif breakage == "history_party":
        root.history[0]["counterparty_id"] = "provider-0"
    elif breakage == "crime_channel":
        root.crime["routing"][-1]["channel"] = "controlled_account"
    else:
        root.crime["source_owner"] = "player"
    with pytest.raises(ValueError):
        m.validate_world(root)


def test_build_audits_full_corpus_and_binds_exact_input_bytes(tmp_path):
    m = module()
    report = m.build_pilot(tmp_path / "pilot")
    assert report["authored_roots"] == 60
    assert report["confirmed_candidate_rows"] == 600
    assert report["reviewed_rows"] == 0 and report["release_ready"] is False
    assert report["combined"]["rows"] == 1076
    assert report["combined"]["components"] >= 1
    import hashlib

    for name, expected in report["source_hashes"].items():
        assert hashlib.sha256((m.ROOT / name).read_bytes()).hexdigest() == expected
    assert report["combined"]["input_hashes"]
    with pytest.raises(FileExistsError):
        m.build_pilot(tmp_path / "pilot")


def test_observation_order_does_not_change_payment_bound_facts():
    m = module()
    world = m.author_roots()[0]
    expected = m.compile_root(world)
    world.observations.reverse()
    actual = m.compile_root(world)
    assert [r["public_snapshot"] for r in actual] == [
        r["public_snapshot"] for r in expected
    ]


@pytest.mark.parametrize(
    "breakage",
    [
        "service_amount",
        "loan_borrower",
        "gift_as_crime",
        "history_direction",
        "future_utc",
        "due_utc",
        "reused_title",
        "missing_history",
    ],
)
def test_review_rejects_causal_and_time_mismatches(breakage):
    m = module()
    source = (
        "service"
        if breakage == "service_amount"
        else "asset"
        if breakage == "reused_title"
        else "debt"
    )
    root = deepcopy(
        next(
            r
            for r in m.author_roots()
            if r.source == source and r.id.split("-")[2] == "3"
        )
    )
    if breakage == "service_amount":
        root.events = [
            replace(e, amount=1) if e.kind == "accepted_service_stage" else e
            for e in root.events
        ]
    elif breakage == "loan_borrower":
        e = next(e for e in root.events if e.kind == "loan_disbursement")
        root.events[root.events.index(e)] = replace(e, beneficiary="provider-0")
        next(h for h in root.history if h["origin_event_id"] == e.id)[
            "counterparty_id"
        ] = "provider-0"
    elif breakage == "gift_as_crime":
        root.events = [
            replace(e, kind="lawful_gift", amount=1)
            if e.kind == "unrelated_funds_entrusted"
            else replace(e, kind="lawful_transfer")
            if e.kind == "escrow_embezzlement"
            else e
            for e in root.events
        ]
    elif breakage == "history_direction":
        root.history[0]["operation_code"] = "incoming_transfer"
    elif breakage == "future_utc":
        root.observations[0] = replace(
            root.observations[0], checked_at="2026-09-13T08:30:00+00:00"
        )
    elif breakage == "due_utc":
        root.obligations[0] = replace(
            root.obligations[0], due="2026-09-13T08:30:00+00:00"
        )
    elif breakage == "missing_history":
        root.history.pop(
            1
        )  # The prior repayment cannot disappear from a complete history.
    else:
        root.rights[1] = deepcopy(root.rights[0])
    with pytest.raises(ValueError):
        m.validate_world(root)


@pytest.mark.parametrize(
    "breakage",
    [
        "missing_control",
        "controller",
        "forged_denial",
        "missing_document",
        "wrong_scope",
        "unsigned",
    ],
)
def test_signed_evidence_and_nominee_control_are_authored_and_bound(breakage):
    m = module()
    root = deepcopy(m.author_roots()[0])
    assert hasattr(root, "evidence_worlds"), (
        "projection lacks independently authored authority worlds"
    )
    positive = root.evidence_worlds["criminal"]
    doc = positive["documents"][root.crime["source_payment"]]["actual_purpose"]
    if breakage == "missing_control":
        positive["account_controls"].clear()
    elif breakage == "controller":
        positive["account_controls"][0]["controller"] = "player"
    elif breakage == "forged_denial":
        doc["outcome"] = "corroborates"
    elif breakage == "missing_document":
        positive["documents"].pop(root.crime["source_payment"])
    elif breakage == "wrong_scope":
        doc["amount"] = 1
    else:
        doc["signed_by_issuer"] = False
    with pytest.raises(ValueError):
        m.validate_world(root)


def test_projected_checks_are_copies_of_scoped_authored_documents():
    m = module()
    root = m.author_roots()[0]
    assert hasattr(root, "evidence_worlds")
    for row in m.compile_root(root):
        key = {0: "lawful", 1: "criminal", None: "unresolved"}[row["aml_label"]]
        world = root.evidence_worlds[key]
        for record in row["economic_records"]:
            kind = (
                "wrong_cover"
                if row["variant_recipe"] == "wrong_cover" and record["step_number"] == 1
                else "actual_purpose"
            )
            assert record["record_check"] == world["documents"][record["id"]][kind]


@pytest.mark.parametrize("defect", ["duplicate_stage", "lawful_crime", "document_kind"])
def test_review_fix1_rejects_reused_stage_and_forged_case_file(defect):
    m = module()
    root = deepcopy(m.author_roots()[0])
    if defect == "duplicate_stage":
        stages = [e for e in root.events if e.kind == "accepted_service_stage"]
        root.events = [
            replace(e, parents=(stages[0].id,) * 3)
            if e.kind == "accepted_work_receivable"
            else e
            for e in root.events
            if e not in stages[1:]
        ]
    elif defect == "lawful_crime":
        source = root.crime["source_payment"]
        root.evidence_worlds["lawful"]["actual_payments"][source].update(
            criminal_proceeds=True
        )
    else:
        source = root.crime["source_payment"]
        root.evidence_worlds["criminal"]["documents"][source]["actual_purpose"][
            "kind"
        ] = "unsigned_customer_rumor"
    with pytest.raises(ValueError):
        m.validate_world(root)
