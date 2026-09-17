"""Freeze independent demo cases and report every predeclared probability band.

This is preflight evidence, not release admission or a claim that a local clock
proves absence of prior training. Training must bind this frozen artifact before
fitting, and rerun independence against every dataset subsequently used.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path

from scripts.aml_dataset.aml_casebook import RESEARCH, ROOT, protocol
from scripts.aml_dataset.aml_provenance import (
    connected_groups,
    digest,
    neutral_observation,
)
from scripts.aml_dataset.aml_review import verify_review_binding
from scripts.aml_dataset.aml_training import (
    check,
    json_bytes,
    jsonl_bytes,
    source_hashes,
    validate_sources,
)
from src.aml_workshop_simulator.schemas.expanded_contract import ClientProfile


def validate_roster(value):
    """Structural checks only; domain/engine/review checks occur during freeze."""
    check(isinstance(value, dict), "Expected demo object")
    check(value.get("version") == "aml-demo-casebook-v1", "Unsupported demo version")
    rounds = value.get("rounds")
    check(isinstance(rounds, list) and len(rounds) == 5, "Exactly five rounds required")
    rows, ids, round_keys, profiles, economic_contexts = [], set(), set(), set(), set()
    for item in rounds:
        check(isinstance(item, dict), "Invalid round")
        key = item.get("round_key")
        check(
            isinstance(key, str) and key and key not in round_keys, "Invalid round key"
        )
        round_keys.add(key)
        check(
            isinstance(item.get("title"), str) and item["title"].strip(),
            "Missing title",
        )
        cases = item.get("cases")
        check(
            isinstance(cases, list) and len(cases) == 5, "Five cases per round required"
        )
        bands, contexts = Counter(), set()
        for case in cases:
            check(isinstance(case, dict), "Invalid case")
            band = case.get("expected_band")
            check(band in {"low", "high", "ambiguous"}, "Invalid expected band")
            bands[band] += 1
            check(
                isinstance(case.get("rationale"), str) and case["rationale"].strip(),
                "Missing rationale",
            )
            row = case.get("record")
            check(isinstance(row, dict), "Missing authored record")
            sid = row.get("scenario_id")
            check(
                isinstance(sid, str) and sid and sid not in ids,
                "Duplicate/missing scenario ID",
            )
            ids.add(sid)
            expected = {"low": 0, "high": 1, "ambiguous": None}[band]
            label = row.get("aml_label")
            check(
                label is None
                if expected is None
                else type(label) is int and label == expected,
                "Expected band/label mismatch",
            )
            public = row.get("public_snapshot", {})
            config = public.get("config", {})
            check(
                isinstance(config.get("behavior", {}).get("profile"), dict),
                "Missing profile",
            )
            contexts.add(digest(config))
            rows.append(row)
        check(
            bands == {"low": 2, "high": 2, "ambiguous": 1},
            "Round band mix must be 2/2/1",
        )
        check(
            len(contexts) == 1, "All participants in a round require identical context"
        )
        config = cases[0]["record"]["public_snapshot"]["config"]
        profile = ClientProfile.model_validate(config["behavior"]["profile"])
        profiles.add((profile.title.strip(), profile.description.strip()))
        # ClientProfile is display text only. Economic differences live in the
        # actual history, counterparties and AML context, not invented fields.
        economic_contexts.add(
            digest(neutral_observation({"config": config, "steps": []}, shape=True))
        )
    check(
        len(profiles) == 5 and len(economic_contexts) == 5,
        "Five different public profiles and economic contexts required",
    )
    return rows


def require_independent(graph, demo_ids, development_ids):
    check(not demo_ids & development_ids, "Demo/development IDs overlap")
    for members in graph["groups"].values():
        members = set(members)
        check(
            not (members & demo_ids and members & development_ids),
            "Demo is related to development through provenance/observations",
        )


def freeze_demo(casebook, development, output):
    """Check complete roster, independent review, engine and cross-corpus closure."""
    casebook, development, output = map(Path, (casebook, development, output))
    check(not output.exists(), "Output already exists")
    raw = casebook.read_bytes()
    value = json.loads(raw)
    rows = validate_roster(value)
    check(
        all(verify_review_binding(row) for row in rows),
        "Every demo record needs bound independent review",
    )
    other_raw = development.read_bytes()
    other = [
        json.loads(line)
        for line in other_raw.decode("utf-8").splitlines()
        if line.strip()
    ]
    check(bool(other), "Complete development corpus is required")
    combined = other + rows
    criteria = protocol()
    features = validate_sources(combined, criteria)
    graph = connected_groups(combined, features)
    demo_ids = {r["scenario_id"] for r in rows}
    require_independent(graph, demo_ids, {r["scenario_id"] for r in other})
    hashes = {
        "source_casebook_sha256": sha256(raw).hexdigest(),
        "development_casebook_sha256": sha256(other_raw).hexdigest(),
    }
    artifacts = {
        "casebook.json": raw,
        "records.jsonl": jsonl_bytes(rows),
        "provenance.json": json_bytes(graph),
        "protocol.json": json_bytes(criteria),
    }
    manifest = {
        "version": "aml-demo-freeze-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "reviewed-financially-valid-demo-independent-of-specified-development-corpus",
        "release_ready": False,
        "independence_requires_recheck_after_development_changes": True,
        "rows": len(rows),
        "rounds": 5,
        **hashes,
        "source_hashes": {
            **source_hashes(),
            **{
                name: sha256((ROOT / name).read_bytes()).hexdigest()
                for name in (
                    "scripts/aml_demo_casebook.py",
                    "scripts/aml_dataset/aml_casebook.py",
                    RESEARCH,
                )
            },
        },
        "artifact_hashes": {
            name: sha256(data).hexdigest() for name, data in artifacts.items()
        },
    }
    # All gates precede output creation. No overwrite/resume and no model access.
    output.mkdir(parents=True, exist_ok=False)
    for name, data in artifacts.items():
        with (output / name).open("xb") as handle:
            handle.write(data)
    with (output / "manifest.json").open("xb") as handle:
        handle.write(json_bytes(manifest))
    return manifest


def evaluate_bands(value, probabilities):
    """Retain every case, including failed bands, using unrounded probabilities."""
    rows = validate_roster(value)
    check(
        set(probabilities) == {r["scenario_id"] for r in rows},
        "Prediction roster mismatch",
    )
    results = []
    for item in value["rounds"]:
        for case in item["cases"]:
            sid = case["record"]["scenario_id"]
            p = probabilities[sid]
            check(
                type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1,
                "Invalid probability",
            )
            band = case["expected_band"]
            passed = (
                None if band == "ambiguous" else p < 0.1 if band == "low" else p >= 0.9
            )
            results.append(
                {
                    "round_key": item["round_key"],
                    "scenario_id": sid,
                    "expected_band": band,
                    "aml_probability": p,
                    "actual_band": "low"
                    if p < 0.1
                    else "high"
                    if p >= 0.9
                    else "review",
                    "band_passed": passed,
                    "rationale": case["rationale"],
                    "public_snapshot": case["record"]["public_snapshot"],
                }
            )
    failed = sum(r["band_passed"] is False for r in results)
    return {
        "scope": "demo-probability-bands-only",
        "release_ready": False,
        "bands_passed": failed == 0,
        "clear_passed": 20 - failed,
        "clear_failed": failed,
        "ambiguous_count": 5,
        "cases": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--casebook", type=Path, required=True)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        freeze_demo(args.casebook, args.development, args.output)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
