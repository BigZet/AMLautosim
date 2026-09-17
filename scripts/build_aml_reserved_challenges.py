"""Materialize preregistered whole-component challenges; keep labels unreviewed."""

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from scripts.aml_dataset import aml_population_author as p
from scripts.audit_aml_history_population import file_hash, require


def build(selection, coverage, output):
    selection, coverage, output = Path(selection), Path(coverage), Path(output)
    require(not output.exists(), "Challenge output already exists")
    receipt = json.loads((selection / "audit.json").read_bytes())
    source_roots = selection / "reserved-worlds.jsonl"
    require(
        file_hash(source_roots) == receipt["artifact_hashes"][source_roots.name],
        "Reserved roots checksum mismatch",
    )
    cov = json.loads((coverage / "audit.json").read_bytes())
    require(
        file_hash(coverage / "casebook.jsonl")
        == cov["artifact_hashes"]["casebook.jsonl"],
        "Coverage source checksum mismatch",
    )
    rows = []
    worlds = [
        p.world_from_dict(json.loads(line))
        for line in source_roots.read_bytes().splitlines()
    ]
    require(
        len(worlds) == len(receipt["reserved_new_combination_components"]) == 5,
        "Reserve roster mismatch",
    )
    for index, world in enumerate(worlds):
        for row in p.compile_variants(world, index % 2):
            row["challenge_set"] = "new-combinations"
            rows.append(row)
    with (coverage / "casebook.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row["family_id"] == "P09":
                row["challenge_set"] = "family-held-out"
                rows.append(row)
            elif row["aml_label"] is None:
                row["challenge_set"] = "unresolved"
                rows.append(row)
    features = p.validate_sources(rows, p.protocol())
    graph = p.connected_groups(rows, features)
    artifacts = dict(
        **{
            "casebook.jsonl": p.jsonl_bytes(rows),
            "features.json": p.json_bytes(features),
            "provenance.json": p.json_bytes(graph),
            "roots.jsonl": source_roots.read_bytes(),
        },
        **{
            "protocol-additions.json": p.json_bytes(
                dict(
                    family_held_out=["P09"],
                    new_combination_scenarios=[
                        r["scenario_id"]
                        for r in rows
                        if r["challenge_set"] == "new-combinations"
                    ],
                    rationale="Whole source-entitlement/provider/deposit combinations reserved before selection and model access; P09 uses genuinely empty recent statements and retains older causal history",
                )
            )
        },
    )
    report = dict(
        scope="unreviewed-independent-challenge-candidates",
        rows=len(rows),
        components=len(graph["groups"]),
        counts=dict(Counter(r["challenge_set"] for r in rows)),
        reviewed_rows=0,
        release_ready=False,
        input_hashes={
            str(selection / "audit.json"): file_hash(selection / "audit.json"),
            str(coverage / "audit.json"): file_hash(coverage / "audit.json"),
        },
        artifact_hashes={
            name: sha256(data).hexdigest() for name, data in artifacts.items()
        },
        source_hashes={
            **p.compiler_hashes(),
            "scripts/build_aml_reserved_challenges.py": file_hash(__file__),
        },
        required_next="Check full retained-universe closure and exact-record independent domain review",
    )
    output.mkdir(parents=True)
    for name, data in artifacts.items():
        (output / name).write_bytes(data)
    (output / "audit.json").write_bytes(p.json_bytes(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("selection", "coverage", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = build(args.selection, args.coverage, args.output)
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("rows", "components", "counts", "release_ready")
            }
        )
    )
