"""Freeze the entire acceptance roster before any demo scoring."""

from copy import deepcopy
import importlib
import json
from functools import lru_cache

import pytest


def module():
    return importlib.import_module("scripts.aml_demo_casebook")


@lru_cache(maxsize=1)
def real_configs():
    from scripts.aml_dataset.aml_world_graph import author_roots, compile_root
    from src.aml_workshop_simulator.schemas.round_config import AMLGameConfigOut

    configs = {}
    for root in author_roots():
        if root.source not in configs:
            config = compile_root(root)[0]["public_snapshot"]["config"]
            AMLGameConfigOut.model_validate({"config_version": "fixture", **config})
            configs[root.source] = config
    return list(configs.values())


def roster():
    rounds = []
    for i in range(5):
        config = deepcopy(real_configs()[i])
        cases = []
        for j, band in enumerate(["low", "low", "high", "high", "ambiguous"]):
            cases.append(
                {
                    "expected_band": band,
                    "rationale": "An authored economic explanation, fixed before scoring.",
                    "record": {
                        "scenario_id": f"case-{i}-{j}",
                        "aml_label": {"low": 0, "high": 1, "ambiguous": None}[band],
                        "public_snapshot": {"config": deepcopy(config), "steps": []},
                    },
                }
            )
        rounds.append(
            {"round_key": f"round-{i}", "title": f"Demo round {i}", "cases": cases}
        )
    return {"version": "aml-demo-casebook-v1", "rounds": rounds}


def test_roster_requires_five_shared_contexts_and_all_25_cases():
    rows = module().validate_roster(roster())
    assert len(rows) == 25


@pytest.mark.parametrize(
    "defect", ["round_count", "mix", "context", "id", "label", "reason", "profile"]
)
def test_invalid_roster_rejected(defect):
    value = roster()
    cases = value["rounds"][0]["cases"]
    if defect == "round_count":
        value["rounds"].pop()
    elif defect == "mix":
        cases.pop()
    elif defect == "context":
        cases[0]["record"]["public_snapshot"]["config"]["behavior"]["profile"][
            "title"
        ] = "changed"
    elif defect == "id":
        cases[0]["record"]["scenario_id"] = cases[1]["record"]["scenario_id"]
    elif defect == "label":
        cases[0]["record"]["aml_label"] = 1
    elif defect == "reason":
        cases[0]["rationale"] = ""
    else:
        for case in value["rounds"][1]["cases"]:
            case["record"]["public_snapshot"]["config"] = deepcopy(
                cases[0]["record"]["public_snapshot"]["config"]
            )
    with pytest.raises(ValueError):
        module().validate_roster(value)


def test_cross_corpus_closure_rejects_hidden_related_cases():
    groups = {"groups": {"a": ["train-1", "demo-1"], "b": ["train-2"]}}
    with pytest.raises(ValueError, match="related"):
        module().require_independent(groups, {"demo-1"}, {"train-1", "train-2"})
    module().require_independent(
        {"groups": {"a": ["demo-1"], "b": ["train-1"]}}, {"demo-1"}, {"train-1"}
    )


def test_band_results_keep_failures_and_do_not_force_ambiguous_to_half():
    m = module()
    predictions = dict(
        zip(
            [r["scenario_id"] for r in m.validate_roster(roster())],
            [0.1, 0.099999, 0.9, 0.899999, 0.97] * 5,
        )
    )
    report = m.evaluate_bands(roster(), predictions)
    assert len(report["cases"]) == 25
    assert report["clear_passed"] == 10
    assert report["clear_failed"] == 10
    assert report["bands_passed"] is False
    assert all(
        c["band_passed"] is None
        for c in report["cases"]
        if c["expected_band"] == "ambiguous"
    )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1, 1.1, True])
def test_invalid_probability_rejected(bad):
    m = module()
    predictions = {r["scenario_id"]: 0.5 for r in m.validate_roster(roster())}
    predictions["case-0-0"] = bad
    with pytest.raises(ValueError):
        m.evaluate_bands(roster(), predictions)


def test_roster_mismatch_rejected_even_if_other_scores_pass():
    with pytest.raises(ValueError, match="roster"):
        module().evaluate_bands(roster(), {"unrelated": 0.01})


def test_invalid_unreviewed_casebook_never_freezes(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(roster()), encoding="utf-8")
    development = tmp_path / "development.jsonl"
    development.write_text("", encoding="utf-8")
    output = tmp_path / "frozen"
    with pytest.raises(ValueError):
        module().freeze_demo(source, development, output)
    assert not output.exists()


def test_cosmetic_profile_changes_do_not_create_five_economic_contexts():
    value = roster()
    same = value["rounds"][0]["cases"][0]["record"]["public_snapshot"]["config"]
    for i, item in enumerate(value["rounds"]):
        for case in item["cases"]:
            config = deepcopy(same)
            config["behavior"]["profile"].update(
                id=f"renamed-{i}", title=f"Title {i}", description=f"Description {i}"
            )
            case["record"]["public_snapshot"]["config"] = config
    with pytest.raises(ValueError, match="economic contexts"):
        module().validate_roster(value)


def test_freeze_binds_the_exact_bytes_used_for_real_corpus_closure(
    tmp_path, monkeypatch
):
    """Isolate roster shape only; real review/engine/closure/hash checks stay on.

    These development records are an IO regression fixture, never an acceptance
    demo. Domain approval is the existing exact review, not fabricated by test.
    """
    from pathlib import Path
    from hashlib import sha256
    from scripts.aml_dataset.aml_training import read_rows, jsonl_bytes

    m = module()
    rows = read_rows(
        Path("resources/aml_dataset/aml-v1/origins-reviewed/v3/casebook.jsonl")
    )

    def family(root):
        return [r for r in rows if r["provenance"]["root_id"] == root]

    demo = family("service_jobs")[:25]
    old = family("loan_consolidation")[:1]
    replacement = family("family_pool")[:1]
    assert len(demo) == 25 and old and replacement
    monkeypatch.setattr(m, "validate_roster", lambda _: demo)
    source = tmp_path / "io-fixture.json"
    source.write_text('{"scope":"IO regression only"}', encoding="utf-8")
    development = tmp_path / "development.jsonl"
    old_bytes = jsonl_bytes(old)
    development.write_bytes(old_bytes)
    actual_read = Path.read_bytes
    reads = []

    def replace_after_read(path):
        raw = actual_read(path)
        if path == development:
            reads.append(path)
            path.write_bytes(jsonl_bytes(replacement))
        return raw

    monkeypatch.setattr(Path, "read_bytes", replace_after_read)
    output = tmp_path / "frozen"
    manifest = m.freeze_demo(source, development, output)
    assert len(reads) == 1
    assert manifest["development_casebook_sha256"] == sha256(old_bytes).hexdigest()
    graph = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
    ids = set(graph["scenario_groups"])
    assert old[0]["scenario_id"] in ids
    assert replacement[0]["scenario_id"] not in ids
    assert len(ids) == 26
    for name, expected in manifest["artifact_hashes"].items():
        assert sha256(actual_read(output / name)).hexdigest() == expected
    assert "protocol.json" in manifest["artifact_hashes"]
    with pytest.raises(ValueError, match="exists"):
        m.freeze_demo(source, development, output)
