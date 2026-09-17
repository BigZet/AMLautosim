"""Frozen acceptance cases must remain independent when development expands."""

from hashlib import sha256
import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    from scripts import aml_demo_casebook as demo
    from scripts.aml_dataset.aml_training import jsonl_bytes, read_rows

    rows = read_rows(
        Path("resources/aml_dataset/aml-v1/origins-reviewed/v3/casebook.jsonl")
    )
    cases = [r for r in rows if r["provenance"]["root_id"] == "service_jobs"][:25]
    development = [
        r for r in rows if r["provenance"]["root_id"] == "loan_consolidation"
    ][:1]
    # IO fixture only: real bound reviews, financial engine and closure remain on.
    # These are existing development records, never the acceptance demo roster.
    monkeypatch.setattr(demo, "validate_roster", lambda value: value["fixture_rows"])
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"fixture_rows": cases}), encoding="utf-8")
    dev = tmp_path / "development.jsonl"
    dev.write_bytes(jsonl_bytes(development))
    output = tmp_path / "frozen"
    demo.freeze_demo(source, dev, output)
    return output, dev, cases


def verifier():
    return importlib.import_module("scripts.aml_demo_training").verify_frozen_demo


def test_verified_receipt_binds_snapshot_and_actual_current_corpus(frozen):
    output, dev, _ = frozen
    receipt, snapshot = verifier()(output, dev)
    assert receipt["demo_rows"] == 25
    assert receipt["development_rows"] == 1
    assert receipt["development_sha256"] == sha256(dev.read_bytes()).hexdigest()
    assert (
        receipt["freeze_manifest_sha256"]
        == sha256(snapshot["manifest.json"]).hexdigest()
    )
    assert receipt["independent"] is True
    assert receipt["required_profiles"] == ["account-holder"]
    assert set(snapshot) == {p.name for p in output.iterdir()}


def test_expanded_development_cannot_include_demo_relative(frozen):
    from scripts.aml_dataset.aml_training import jsonl_bytes

    output, dev, cases = frozen
    # Adding the exact record is a real new leak; old freeze manifest stays valid.
    with dev.open("ab") as handle:
        handle.write(jsonl_bytes(cases[:1]))
    with pytest.raises(ValueError, match="overlap|Duplicate"):
        verifier()(output, dev)


def test_new_distinct_id_from_same_history_is_rejected(frozen):
    from scripts.aml_dataset.aml_training import jsonl_bytes, read_rows

    output, dev, cases = frozen
    rows = read_rows(
        Path("resources/aml_dataset/aml-v1/origins-reviewed/v3/casebook.jsonl")
    )
    sibling = next(
        r
        for r in rows
        if r["provenance"]["root_id"] == "service_jobs"
        and r["scenario_id"] not in {c["scenario_id"] for c in cases}
    )
    with dev.open("ab") as handle:
        handle.write(jsonl_bytes([sibling]))
    with pytest.raises(ValueError, match="related"):
        verifier()(output, dev)


def test_rehashing_envelope_cannot_approve_altered_reviewed_record(frozen):
    from scripts.aml_dataset.aml_training import jsonl_bytes

    output, dev, _ = frozen
    manifest = json.loads((output / "manifest.json").read_bytes())
    casebook = json.loads((output / "casebook.json").read_bytes())
    casebook["fixture_rows"][0]["review_status"] = "authored_unreviewed"
    payloads = {
        "casebook.json": json.dumps(casebook).encode(),
        "records.jsonl": jsonl_bytes(casebook["fixture_rows"]),
    }
    for name, raw in payloads.items():
        (output / name).write_bytes(raw)
        manifest["artifact_hashes"][name] = sha256(raw).hexdigest()
    manifest["source_casebook_sha256"] = manifest["artifact_hashes"]["casebook.json"]
    (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="review binding"):
        verifier()(output, dev)


@pytest.mark.parametrize(
    "defect", ["checksum", "missing", "extra", "source", "roster", "protocol"]
)
def test_malformed_frozen_snapshot_is_rejected(frozen, defect):
    output, dev, _ = frozen
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if defect == "checksum":
        (output / "casebook.json").write_bytes(b"{}")
    elif defect == "missing":
        del manifest["artifact_hashes"]["records.jsonl"]
    elif defect == "extra":
        (output / "untracked.json").write_bytes(b"{}")
    elif defect == "source":
        manifest["source_hashes"] = {}
    else:
        name = "records.jsonl" if defect == "roster" else "protocol.json"
        raw = b"{}\n"
        (output / name).write_bytes(raw)
        manifest["artifact_hashes"][name] = sha256(raw).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        verifier()(output, dev)


def test_snapshot_is_captured_once_before_closure(frozen, monkeypatch):
    output, dev, _ = frozen
    actual = Path.read_bytes
    old = actual(dev)
    reads = []

    def replace_after_read(path):
        raw = actual(path)
        if path == dev:
            reads.append(path)
            path.write_bytes(b"{}\n")
        return raw

    monkeypatch.setattr(Path, "read_bytes", replace_after_read)
    receipt, _ = verifier()(output, dev)
    assert reads == [dev]
    assert receipt["development_sha256"] == sha256(old).hexdigest()
