"""Bind predeclared acceptance cases to each actual training corpus before fit.

The freeze timestamp is provenance, not proof that no earlier model was fitted.
No demo predictions or labels are passed to model selection by this module.
"""

from hashlib import sha256
import json
from pathlib import Path

from scripts import aml_demo_casebook as demo
from scripts.aml_dataset.aml_training import check, jsonl_bytes, source_hashes


def verify_frozen_demo(directory, development):
    """Return a reproducible receipt and the exact verified artifact bytes.

    Recompute closure against the complete current corpus, including diagnostics
    and holdouts; the corpus used when the demo was first frozen may be smaller.
    """
    directory, development = Path(directory), Path(development)
    names = {"casebook.json", "records.jsonl", "provenance.json", "protocol.json"}
    check(
        {
            p.relative_to(directory).as_posix()
            for p in directory.rglob("*")
            if p.is_file()
        }
        == names | {"manifest.json"},
        "Unexpected or missing frozen demo artifacts",
    )
    snapshot = {
        name: (directory / name).read_bytes()
        for name in sorted(names | {"manifest.json"})
    }
    manifest = json.loads(snapshot["manifest.json"])
    check(
        manifest.get("version") == "aml-demo-freeze-v1"
        and manifest.get("rows") == 25
        and manifest.get("rounds") == 5
        and manifest.get("release_ready") is False
        and manifest.get("independence_requires_recheck_after_development_changes")
        is True,
        "Invalid frozen demo manifest",
    )
    hashes = manifest.get("artifact_hashes", {})
    check(set(hashes) == names, "Incomplete frozen demo hashes")
    for name in names:
        check(
            sha256(snapshot[name]).hexdigest() == hashes[name],
            f"Frozen demo checksum mismatch: {name}",
        )
    expected_sources = {
        **source_hashes(),
        **{
            name: sha256((demo.ROOT / name).read_bytes()).hexdigest()
            for name in (
                "scripts/aml_demo_casebook.py",
                "scripts/aml_dataset/aml_casebook.py",
                demo.RESEARCH,
            )
        },
    }
    check(
        manifest.get("source_hashes") == expected_sources, "Frozen demo source mismatch"
    )
    check(
        manifest.get("source_casebook_sha256") == hashes["casebook.json"],
        "Frozen demo casebook binding mismatch",
    )
    rules = json.loads(snapshot["protocol.json"])
    check(rules == demo.protocol(), "Frozen demo protocol mismatch")
    rows = demo.validate_roster(json.loads(snapshot["casebook.json"]))
    check(len(rows) == 25, "Frozen demo roster must contain 25 rows")
    check(
        snapshot["records.jsonl"] == jsonl_bytes(rows),
        "Frozen demo record roster mismatch",
    )
    check(
        all(demo.verify_review_binding(row) for row in rows),
        "Frozen demo review binding failed",
    )
    raw = development.read_bytes()
    other = [
        json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()
    ]
    check(bool(other), "Complete current development corpus required")
    demo_ids, development_ids = (
        {r["scenario_id"] for r in rows},
        {r["scenario_id"] for r in other},
    )
    check(not demo_ids & development_ids, "Demo/development IDs overlap")
    combined = other + rows
    features = demo.validate_sources(combined, rules)
    graph = demo.connected_groups(combined, features)
    demo.require_independent(graph, demo_ids, development_ids)
    return {
        "version": "aml-demo-training-binding-v1",
        "freeze_manifest_sha256": sha256(snapshot["manifest.json"]).hexdigest(),
        "casebook_sha256": hashes["casebook.json"],
        "development_sha256": sha256(raw).hexdigest(),
        "closure_sha256": demo.digest(graph),
        "demo_rows": len(rows),
        "development_rows": len(other),
        "required_profiles": sorted(
            {
                row["public_snapshot"]["config"]["behavior"]["profile"]["id"]
                for row in rows
            }
        ),
        "independent": True,
    }, snapshot
