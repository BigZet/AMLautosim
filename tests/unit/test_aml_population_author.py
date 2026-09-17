"""Actual provider topology and balance-after-deposit population grammar."""

import importlib
import importlib.util
from copy import deepcopy
from dataclasses import replace
import pytest


def module():
    name = "scripts.aml_dataset.aml_population_author"
    assert importlib.util.find_spec(name), "population topology author missing"
    return importlib.import_module(name)


def test_canonical_provider_partitions_are_real_relationships():
    m = module()
    partitions = m.provider_partitions(6)
    assert len(partitions) == 203
    assert len(set(partitions)) == 203
    assert partitions[0] == (0, 0, 0, 0, 0, 0)
    assert partitions[-1] == (0, 1, 2, 3, 4, 5)
    for topology in (partitions[0], partitions[-1]):
        w = m.author_world("service", (1, 1, 1), topology)
        m.graph.validate_world(w)
        debits = [p for p in w.payments if p.operation == "card_transfer"]
        assert len(debits) == 6 and sum(p.amount for p in debits) == 400000
        assert len({p.beneficiary for p in debits}) == len(set(topology))
        assert len(w.history) == 6


@pytest.mark.parametrize(
    "defect",
    [
        "deposit_amount",
        "wrong_provider",
        "reuse_contract",
        "missing_deposit",
        "delivery_amount",
    ],
)
def test_actual_deposit_contract_and_delivery_are_bound(defect):
    m = module()
    w = deepcopy(m.author_world("service", (1, 1, 1), (0, 0, 1, 2, 3, 4)))
    deposits = [e for e in w.events if e.kind == "service_deposit_paid"]
    balances = [e for e in w.events if e.kind == "service_balance_due"]
    if defect == "deposit_amount":
        e = deposits[0]
        w.events[w.events.index(e)] = replace(e, amount=1)
        next(h for h in w.history if h["origin_event_id"] == e.id)["amount"] = "1.00"
    elif defect == "wrong_provider":
        e = deposits[0]
        w.events[w.events.index(e)] = replace(e, beneficiary="source-0")
        next(h for h in w.history if h["origin_event_id"] == e.id)[
            "counterparty_id"
        ] = "source-0"
    elif defect == "reuse_contract":
        e = balances[1]
        w.events[w.events.index(e)] = replace(e, parents=balances[0].parents)
    elif defect == "missing_deposit":
        w.history.pop()
    else:
        e = next(e for e in w.events if e.kind == "service_contract_completed")
        w.events[w.events.index(e)] = replace(e, amount=1)
    with pytest.raises(ValueError):
        m.graph.validate_world(w)


@pytest.mark.parametrize(
    "kind",
    [
        "foreign_bank",
        "payment_service",
        "crypto_p2p",
        "exchange_withdrawal",
        "inactive_restart",
    ],
)
def test_retired_profile_constructions_are_rejected(kind):
    m = module()
    w = m.author_role_world(
        m.author_world("asset", (2, 1), (0, 0, 1, 2, 3, 4)), "collection_owner"
    )
    # The accepted curriculum uses one fixed history, not these extra profiles.
    # Current incoming-kind coverage is checked in test_attribute_curriculum.py.
    with pytest.raises(ValueError, match='unsupported authored coverage construction'):
        m.author_coverage_case(w, kind)


def test_all_source_grammars_and_schedules_pass_unchanged_finances():
    m = module()
    from scripts.aml_dataset.aml_training import validate_sources
    from scripts.aml_dataset.aml_casebook import protocol

    for source in ("service", "asset", "refund", "debt", "cost"):
        for incoming in ((3,), (2, 1), (1, 1, 1)):
            w = m.author_world(source, incoming, (0, 0, 1, 2, 3, 4))
            rows = m.compile_variants(w, extra_label=0)
            assert len(rows) == 25
            assert sum(r["aml_label"] == 0 for r in rows) == 13
            assert sum(r["aml_label"] == 1 for r in rows) == 12
            assert len(validate_sources(rows, protocol())) == 25
            opaque = [r for r in rows if r["variant_recipe"] == "schedule-0-opaque"]
            assert opaque[0]["public_snapshot"] == opaque[1]["public_snapshot"]


def test_probe_reports_empirical_closure_and_binds_written_rows(tmp_path):
    m = module()
    worlds = [
        m.author_world("service", (1, 1, 1), p) for p in m.provider_partitions(6)[:4]
    ]
    report = m.audit_probe(worlds, tmp_path / "probe")
    assert report["authored_roots"] == 4 and report["rows"] == 8
    assert 0 < report["components"] <= 4
    assert report["feature_conflicts"] > 0
    from hashlib import sha256

    assert (
        sha256((tmp_path / "probe/casebook.jsonl").read_bytes()).hexdigest()
        == report["artifact_hashes"]["casebook.jsonl"]
    )


def test_prefit_availability_mix_retains_third_opaque_pair_as_diagnostics():
    m = module()
    w = m.author_world("service", (1, 1, 1), (0, 0, 1, 2, 3, 4))
    rows = m.compile_variants(w, 1)
    assert len([r for r in rows if r["variant_recipe"].endswith("-opaque")]) == 4
    assert (
        len([r for r in rows if r["variant_recipe"] == "schedule-2-wrong_cover"]) == 2
    )
    diagnostics = m.compile_diagnostics(w)
    assert len(diagnostics) == 2
    assert {r["aml_label"] for r in diagnostics} == {0, 1}
    assert diagnostics[0]["public_snapshot"] == diagnostics[1]["public_snapshot"]
    assert all(r["provenance"]["root_id"] == w.id for r in diagnostics)
    assert len(m.validate_sources(rows + diagnostics, m.protocol())) == 27


def test_closure_projection_preserves_every_supported_ancestry_field():
    m = module()
    rows = m.compile_probe_rows(m.author_world("service", (3,), (0, 1, 2, 3, 4, 5)))
    rows[0].update(
        parent_ids=["external-parent"], history_origin_ids=["external-history"]
    )
    features = m.validate_sources(rows, m.protocol())
    assert m.connected_groups(rows, features) == m.connected_groups(
        [m.closure_row(r) for r in rows], features
    )
    assert m.closure_row(rows[0])["parent_ids"] == ["external-parent"]


def test_role_dossier_binds_actual_activity_contracts_and_assets():
    m = module()
    base = m.author_world("asset", (2, 1), (0, 0, 1, 2, 3, 4))
    w = m.author_role_world(base, "collection_owner")
    m.validate_role_world(w)
    assert w.profile["id"] == "collection_owner"
    assert w.activity["asset_membership"]
    altered = deepcopy(w)
    altered.activity["source_contracts"][0]["basis"] = "invented-event"
    with pytest.raises(ValueError, match="activity"):
        m.validate_role_world(altered)
    with pytest.raises(ValueError, match="incompatible"):
        m.author_role_world(
            m.author_world("service", (3,), (0, 1, 2, 3, 4, 5)), "collection_owner"
        )
    originals = m.compile_variants(base, 0)
    assigned = m.compile_variants(w, 0)
    assert m.validate_sources(originals, m.protocol()) == m.validate_sources(
        assigned, m.protocol()
    )


def test_quota_matching_never_duplicates_component_and_reports_shortfall():
    m = module()
    candidates = {"a": {"collection_owner", "artisan_owner"}, "b": {"artisan_owner"}}
    assert m.assign_roles(candidates, {"collection_owner": 1, "artisan_owner": 1}) == {
        "a": "collection_owner",
        "b": "artisan_owner",
    }
    with pytest.raises(ValueError, match="quota"):
        m.assign_roles(candidates, {"collection_owner": 2, "artisan_owner": 1})


def test_world_serialization_preserves_explicit_typed_authorities():
    m = module()
    w = m.author_role_world(
        m.author_world("debt", (2, 1), (0, 0, 1, 2, 3, 4)), "equipment_pool_organizer"
    )
    restored = m.world_from_dict(m.asdict(w))
    m.validate_role_world(restored)
    assert m.asdict(restored) == m.asdict(w)


def test_selected_compilation_keeps_raw_ancestry_and_diagnostic_exclusion():
    m = module()
    w = m.author_role_world(
        m.author_world("refund", (3,), (0, 0, 1, 2, 3, 4)), "event_organizer"
    )
    selection = dict(
        root_id=w.id,
        profile=w.profile["id"],
        extra_label=0,
        parent_ids=[w.id + "-opaque-0", w.id + "-opaque-1", "other-raw-sibling"],
        activity_sha256=m.digest(w.activity),
    )
    main, diagnostics = m.compile_selected(w, selection)
    assert len(main) == 25 and len(diagnostics) == 2
    assert all(
        r["provenance"]["parent_ids"] == selection["parent_ids"]
        for r in main + diagnostics
    )
    assert all(r.get("challenge_set") == "masked-context" for r in diagnostics)
    assert all(r.get("challenge_set") is None for r in main)
    assert all(r["activity_dossier"] == w.activity for r in main + diagnostics)
    assert len(m.validate_sources(main + diagnostics, m.protocol())) == 27


@pytest.mark.parametrize(
    "source,role,required",
    [
        ("debt", "equipment_pool_organizer", "equipment_purchase_paid"),
        ("refund", "artisan_owner", "restoration_work_started"),
        ("asset", "artisan_owner", "restoration_work_started"),
        ("debt", "project_coordinator", "coordination_mandate"),
        ("refund", "event_organizer", "programme_organisation_agreement"),
    ],
)
def test_role_requires_actual_engagement_or_owned_shared_equipment(
    source, role, required
):
    m = module()
    w = m.author_role_world(m.author_world(source, (2, 1), (0, 0, 1, 2, 3, 4)), role)
    records = w.activity["activity_events"]
    event = next(e for e in records if e["kind"] == required)
    assert event["parents"] and event["at"].endswith("+03:00")
    bad = deepcopy(w)
    bad.activity["activity_events"].remove(event)
    with pytest.raises(ValueError, match="activity"):
        m.validate_role_world(bad)
    assert len(w.history) == len(
        m.author_world(source, (2, 1), (0, 0, 1, 2, 3, 4)).history
    )


@pytest.mark.parametrize(
    "defect", ["parents", "component", "extra", "quota", "candidates"]
)
def test_build_rejects_tampered_selection_before_output(tmp_path, defect):
    m = module()
    probe = tmp_path / "probe"
    m.audit_probe(
        [m.author_world(s, (3,), (0, 0, 1, 2, 3, 4)) for s in ("asset", "debt")], probe
    )
    external = tmp_path / "external"
    external.mkdir()
    (external / "provenance.json").write_bytes((probe / "provenance.json").read_bytes())
    (external / "audit.json").write_bytes(
        m.json_bytes(dict(demo_crossing_components=[], crossing_components={}))
    )
    directory = tmp_path / "selection"
    m.prepare_selection(
        probe,
        external,
        directory,
        {"collection_owner": 1, "equipment_pool_organizer": 1},
    )
    m.validate_saved_selection(directory)
    path = directory / "selection.json"
    value = m.json.loads(path.read_bytes())
    if defect == "parents":
        value["selections"][0]["parent_ids"] = []
    elif defect == "component":
        value["selections"][0]["raw_component"] = "invented-independent-group"
    elif defect == "extra":
        value["selections"][0]["extra_label"] = 1
    elif defect == "quota":
        value["quotas"]["collection_owner"] = 2
    else:
        (directory / "activity-candidates.jsonl").write_bytes(b"{}\n")
    path.write_bytes(m.json_bytes(value))
    with pytest.raises(ValueError, match="selection|candidate|quota"):
        m.build_population(directory, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_small_build_and_complete_closure_bind_actual_written_population(tmp_path):
    m = module()
    probe = tmp_path / "probe"
    m.audit_probe(
        [m.author_world(s, (3,), (0, 0, 1, 2, 3, 4)) for s in ("asset", "debt")], probe
    )
    external = tmp_path / "external"
    external.mkdir()
    (external / "provenance.json").write_bytes((probe / "provenance.json").read_bytes())
    (external / "audit.json").write_bytes(
        m.json_bytes(dict(demo_crossing_components=[], crossing_components={}))
    )
    selection = tmp_path / "selection"
    m.prepare_selection(
        probe,
        external,
        selection,
        {"collection_owner": 1, "equipment_pool_organizer": 1},
    )
    report = m.build_population(selection, tmp_path / "population")
    assert report["counts"] == {"main.jsonl": 50, "diagnostics.jsonl": 4}
    assert report["classes"] == {"0": 25, "1": 25}
    assert report["uniform_25"] and report["components"] == 2
    dev = tmp_path / "dev.jsonl"
    demo = tmp_path / "demo.jsonl"
    for path, source in ((dev, "service"), (demo, "refund")):
        path.write_bytes(
            m.jsonl_bytes(
                m.compile_probe_rows(
                    m.author_world(source, (1, 1, 1), (0, 1, 2, 3, 4, 5))
                )
            )
        )
    audit = m.audit_complete_population(
        tmp_path / "population", probe, dev, demo, tmp_path / "closure"
    )
    assert audit["rows"] == 62 and audit["main_components"] == 2 and audit["uniform_25"]
    assert not audit["demo_crossing_components"]
    with (tmp_path / "population/main.jsonl").open("ab") as handle:
        handle.write(b"\n")
    with pytest.raises((ValueError, m.json.JSONDecodeError)):
        m.audit_complete_population(
            tmp_path / "population", probe, dev, demo, tmp_path / "bad-closure"
        )


@pytest.mark.parametrize("kind", ["cash", "salary_purchase"])
def test_coverage_cash_and_payroll_are_actual_bound_worlds(kind):
    m = module()
    w = m.author_role_world(
        m.author_world("service", (1, 1, 1), (0, 0, 1, 2, 3, 4)), "artisan_owner"
    )
    case = m.author_coverage_case(w, kind)
    rows = m.compile_coverage_case(case)
    assert len(rows) == 2 and {r["aml_label"] for r in rows} == {0, 1}
    assert len(m.validate_sources(rows, m.protocol())) == 2
    assert {r["family_id"] for r in rows} == ({"P05"} if kind == "cash" else {"P10"})
    if kind == "salary_purchase":
        assert all(len(r["public_snapshot"]["steps"]) == 11 for r in rows)
        bad = deepcopy(case)
        bad["supplement"]["payments"][0]["actual_beneficiary"] = "collector"
    else:
        assert all(
            any(
                s["card"]["code"] == "cash_withdrawal"
                for s in r["public_snapshot"]["steps"]
            )
            for r in rows
        )
        bad = deepcopy(case)
        bad["settlement_world"]["crime"]["routing"][0]["channel"] = "controlled_account"
    with pytest.raises(ValueError):
        m.compile_coverage_case(bad)


def test_activity_chronology_uses_actual_foundation_before_equipment_purchase():
    m = module()
    w = m.author_world("debt", (2, 1), (0, 0, 1, 2, 3, 4))
    w.events = [
        replace(
            e, at=(m.datetime.fromisoformat(e.at) - m.timedelta(days=20)).isoformat()
        )
        for e in w.events
    ]
    for h in w.history:
        h["occurred_at"] = (
            m.datetime.fromisoformat(h["occurred_at"]) - m.timedelta(days=20)
        ).isoformat()
    w.evidence_worlds = m.graph.author_evidence_worlds(w)
    assigned = m.author_role_world(w, "equipment_pool_organizer")
    records = assigned.activity["activity_events"]
    known = {e.id: m.datetime.fromisoformat(e.at) for e in assigned.events}
    for record in records:
        at = m.datetime.fromisoformat(record["at"])
        assert all(known[parent] < at for parent in record["parents"])
        known[record["id"]] = at


@pytest.mark.parametrize(
    "defect",
    [
        None,
        "receiver",
        "receipt_amount",
        "withdrawal_owner",
        "missing_history",
        "receipt_parent",
    ],
)
def test_cash_deposit_history_requires_actual_withdrawal_handover_and_receipt(defect):
    m = module()
    w = m.author_world(
        "service",
        (1, 1, 1),
        (0, 0, 1, 2, 3, 4),
        deposit_channels=("cash", "card", "card", "card", "card", "card"),
    )
    if defect is None:
        m.graph.validate_world(w)
        role = m.author_role_world(w, "artisan_owner")
        rows = m.compile_probe_rows(role) + m.compile_coverage_case(
            m.author_coverage_case(role, "cash")
        )
        assert len(m.validate_sources(rows, m.protocol())) == 4
        assert any(
            h["operation_code"] == "cash_withdrawal" and h["counterparty_id"] is None
            for h in w.history
        )
        return
    if defect == "missing_history":
        w.history = [h for h in w.history if h["operation_code"] != "cash_withdrawal"]
    else:
        kind = {
            "receiver": "cash_service_deposit_handed_over",
            "receipt_amount": "signed_service_deposit_cash_receipt",
            "withdrawal_owner": "cash_withdrawn_for_service_deposit",
            "receipt_parent": "signed_service_deposit_cash_receipt",
        }[defect]
        event = next(e for e in w.events if e.kind == kind)
        changes = (
            {"beneficiary": "source-0"}
            if defect == "receiver"
            else {"amount": event.amount + 1}
            if defect == "receipt_amount"
            else {"actor": "source-0"}
            if defect == "withdrawal_owner"
            else {"parents": ()}
        )
        w.events[w.events.index(event)] = replace(event, **changes)
    with pytest.raises(ValueError):
        m.graph.validate_world(w)
