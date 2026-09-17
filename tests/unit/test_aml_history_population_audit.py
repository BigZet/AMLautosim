from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json

import pytest

from scripts.audit_aml_history_population import audit, check_economics
from scripts.aml_dataset import aml_population_author as p
from scripts.aml_dataset.aml_population_rails import author_route, compile_route


@pytest.fixture(scope="module")
def rows():
    world = p.author_role_world(
        p.author_world("asset", (1, 1, 1), (0, 0, 1, 2, 3, 4)),
        "collection_owner",
    )
    return (
        p.compile_variants(world, 0)
        + p.compile_coverage_case(p.author_coverage_case(world, "salary_purchase"))
        + p.compile_coverage_case(p.author_coverage_case(world, "cash"))
        + compile_route(author_route(world, "crypto_p2p"))
    )


def test_saved_economic_records_are_consistent(rows):
    for row in rows:
        check_economics(row)


@pytest.mark.parametrize(
    "defect", ["label", "amount", "sender", "conversion", "chronology"]
)
def test_saved_record_mutations_fail_even_with_unchanged_public_schema(rows, defect):
    row = deepcopy(rows[-1])
    record = next(r for r in row["economic_records"] if "settlement_route" in r)
    if defect == "label":
        row["aml_label"] = 1 - row["aml_label"]
    elif defect == "amount":
        record["amount"] = "1.00"
    elif defect == "sender":
        row["public_snapshot"]["steps"][record["step_number"] - 1]["sender_id"] = (
            "someone-else"
        )
    elif defect == "conversion":
        record["settlement_route"]["events"][1]["units"] = "999.00"
    else:
        record["settlement_route"]["events"][0]["at"] = "2099-01-01T00:00:00+03:00"
    with pytest.raises(ValueError, match="mismatch"):
        check_economics(row)


@pytest.mark.parametrize("defect", [None, "incomplete_policy", "checksum", "nonfinite"])
def test_complete_audit_checks_preregistered_roster_and_saved_artifacts(
    tmp_path, defect
):
    channels = ("cash", "card", "card", "card", "card", "card")
    world = p.author_role_world(
        p.author_world("service", (3,), (0, 0, 0, 0, 0, 0), channels), "artisan_owner"
    )
    records = (
        p.compile_probe_rows(world)
        + p.compile_variants(world, 0)
        + p.compile_diagnostics(world)
    )
    for kind in ("cash", "salary_purchase"):
        records += p.compile_coverage_case(p.author_coverage_case(world, kind))
    records += compile_route(author_route(world, "payment_service"))
    vectors = p.validate_sources(records, p.protocol())
    if defect == "nonfinite":
        next(iter(vectors.values()))["observed_inactivity"] = float("nan")
    source = tmp_path / "generator.py"
    source.write_text("# captured generator\n")
    sources = {str(source): sha256(source.read_bytes()).hexdigest()}
    directory = tmp_path / "population"
    directory.mkdir()
    artifacts = {
        "roots.jsonl": p.jsonl_bytes([asdict(world)]),
        "casebook.jsonl": p.jsonl_bytes(records),
        "features.json": json.dumps(vectors).encode(),
        "reused-roots.json": b"[]",
    }
    for name, data in artifacts.items():
        (directory / name).write_bytes(data)
    (directory / "audit.json").write_bytes(
        p.json_bytes(
            dict(
                source_changed_during_build=False,
                source_hashes=sources,
                artifact_hashes={
                    k: sha256(v).hexdigest() for k, v in artifacts.items()
                },
                roots=1,
                rows=39,
                components=1,
                reused_roots=0,
            )
        )
    )
    (directory / "prefit-policy.json").write_bytes(
        p.json_bytes(
            dict(
                source_hashes=sources,
                sources=["service", "asset"]
                if defect == "incomplete_policy"
                else ["service"],
                incoming=[[3]],
                providers=[[0, 0, 0, 0, 0, 0]],
                patterns=[channels],
            )
        )
    )
    if defect == "checksum":
        with (directory / "casebook.jsonl").open("ab") as handle:
            handle.write(b"\n")
    output = tmp_path / "result.json"
    if defect:
        with pytest.raises(ValueError):
            audit(directory, output)
        assert not output.exists()
    else:
        result = audit(directory, output)
        assert result["rows"] == 39
        assert result["independent_domain_review"] is False
        assert result["release_ready"] is False
