from collections import Counter
from dataclasses import asdict
from hashlib import sha256

import pytest

from scripts.aml_dataset import aml_population_author as p
from scripts.build_aml_closed_population import compile_unit
from scripts.audit_aml_closed_population import audit


@pytest.mark.parametrize(
    "source,role", [("service", "artisan_owner"), ("asset", "collection_owner")]
)
def test_uniform_units_preserve_both_truths_and_real_channel_coverage(source, role):
    world = p.author_role_world(
        p.author_world(source, (1, 1, 1), (0, 0, 1, 2, 3, 4)), role
    )
    selection = dict(
        root_id=world.id,
        profile=role,
        activity_sha256=p.digest(world.activity),
        extra_label=0,
        parent_ids=["original-universe-anchor"],
        coverage_kinds=["cash", "salary_purchase"],
        rails=["payment_service", "crypto_p2p", "exchange_withdrawal"]
        if source == "asset"
        else ["payment_service"],
    )
    rows, ids, features = compile_unit((asdict(world), selection))
    main = [r for r in rows if r["scenario_id"] in ids]
    assert len(main) == 25
    assert Counter(r["aml_label"] for r in main) == {0: 13, 1: 12}
    assert len(features) == len(rows) == (52 if source == "asset" else 40)
    assert all(r["review_status"] == "authored_unreviewed" for r in rows)
    assert all(
        "original-universe-anchor" in r["provenance"]["parent_ids"] for r in rows
    )
    for channel in ["bank_transfer", "payment_service", "cash_withdrawal", "salary"] + (
        ["crypto_p2p", "exchange_withdrawal"] if source == "asset" else []
    ):
        assert {
            r["aml_label"]
            for r in main
            if any(
                s.get("action_details", {}).get("incoming_kind", s["card"]["code"])
                == channel
                for s in r["public_snapshot"]["steps"]
            )
        } == {0, 1}
    selection["activity_sha256"] = "not-the-selected-world"
    with pytest.raises(ValueError, match="binding mismatch"):
        compile_unit((asdict(world), selection))


@pytest.mark.parametrize("crossing", [False, True])
def test_final_audit_uses_whole_universe_and_never_approves_small_draft(
    tmp_path, crossing
):
    world = p.author_role_world(
        p.author_world("service", (3,), (0, 0, 1, 2, 3, 4)), "artisan_owner"
    )
    selection = dict(
        root_id=world.id,
        profile="artisan_owner",
        activity_sha256=p.digest(world.activity),
        extra_label=0,
        parent_ids=[],
    )
    rows, ids, features = compile_unit((asdict(world), selection))
    main = [r for r in rows if r["scenario_id"] in ids]
    population, universe = tmp_path / "population", tmp_path / "universe"
    population.mkdir()
    universe.mkdir()
    data = {"main.jsonl": p.jsonl_bytes(main), "features.json": p.json_bytes(features)}
    for name, raw in data.items():
        (population / name).write_bytes(raw)
    receipt = p.json_bytes(
        dict(artifact_hashes={k: sha256(v).hexdigest() for k, v in data.items()})
    )
    (population / "audit.json").write_bytes(receipt)
    members = ["main:" + r["scenario_id"] for r in rows]
    if crossing:
        members.append("demo:reserved-case")
    graph = p.json_bytes(
        dict(
            groups={"closed-group": members},
            scenario_groups={sid: "closed-group" for sid in members},
        )
    )
    (universe / "provenance.json").write_bytes(graph)
    (universe / "audit.json").write_bytes(
        p.json_bytes(
            dict(
                input_hashes={
                    str(population / "audit.json"): sha256(receipt).hexdigest()
                },
                provenance_sha256=sha256(graph).hexdigest(),
                demo_crossings=["closed-group"] if crossing else [],
            )
        )
    )
    report = audit(population, universe, tmp_path / "result.json")
    assert report["main_rows"] == 25 and report["closed_main_groups"] == 1
    assert report["checks"]["no_reserved_component_crossings"] is not crossing
    assert report["checks"]["minimum_1200_closed_main_groups"] is False
    assert report["generation_and_structural_checks_passed"] is False
    assert report["release_ready"] is False
    assert report["conflicting_feature_rows"] >= 4
