"""Read-back integrity and economic consistency audit; never domain approval."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from itertools import product
import json
import math
from pathlib import Path

from scripts.aml_dataset import aml_population_author as p
from scripts.aml_dataset.aml_labels import validate_label, validate_public
from scripts.aml_dataset.aml_training import FEATURE_NAMES


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_hash(path):
    with Path(path).open("rb") as handle:
        return sha256_stream(handle)


def sha256_stream(handle):
    digest = sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def check_economics(row):
    """Cross-check saved truth, operations and routes without assigning labels."""
    validate_label(row)
    validate_public(row["public_snapshot"])
    truth = row["author_truth"]
    require(
        truth["aml_episode_present"] is bool(row["aml_label"]), "Truth/label mismatch"
    )
    require(
        bool(truth["criminal_episode"]) == bool(row["aml_label"]),
        "Criminal episode mismatch",
    )
    records = row["economic_records"]
    steps = row["public_snapshot"]["steps"]
    actual = {item["id"]: item for item in truth["actual_payments"]}
    require(
        len(actual) == len(records) == len(steps), "Economic record roster mismatch"
    )
    for index, (record, step) in enumerate(zip(records, steps, strict=True), 1):
        payment = record["actual_payment"]
        require(record["step_number"] == index, "Economic sequence mismatch")
        require(payment == actual[record["id"]], "Actual payment mismatch")
        require(
            Decimal(record["amount"])
            == Decimal(step["amount"])
            == Decimal(payment["amount"]),
            "Economic amount mismatch",
        )
        require(
            record["operation"] == step["card"]["code"], "Economic operation mismatch"
        )
        route = record.get("settlement_route")
        if route:
            require(
                payment["payer"] == step["sender_id"] == route["observed_sender"],
                "Settlement sender mismatch",
            )
            events = route["events"]
            require(
                all(
                    datetime.fromisoformat(a["at"]) <= datetime.fromisoformat(b["at"])
                    for a, b in zip(events, events[1:])
                ),
                "Settlement chronology mismatch",
            )
            require(
                payment["settlement_event"] == events[-1]["id"],
                "Settlement event mismatch",
            )
            require(
                payment["original_funding_party"]
                == route["original_actual_payment"]["payer"],
                "Funding party mismatch",
            )
            require(
                Decimal(events[0]["amount"])
                == Decimal(events[-1]["amount"])
                == Decimal(step["amount"]),
                "Settlement amount mismatch",
            )
            require(Decimal(events[-1]["fee"]) == 0, "Unexpected settlement fee")
            if route["rail"] != "payment_service":
                conversion = events[1]
                require(
                    Decimal(conversion["units"])
                    * Decimal(conversion["contractual_rub_per_unit"])
                    == Decimal(conversion["rub_value"])
                    == Decimal(step["amount"]),
                    "Conversion conservation mismatch",
                )


def audit(directory, output):
    directory, output = Path(directory), Path(output)
    require(not output.exists(), "Audit output already exists")
    receipt = json.loads((directory / "audit.json").read_bytes())
    require(
        receipt.get("source_changed_during_build") is False,
        "Generation sources changed",
    )
    for name, expected in receipt["source_hashes"].items():
        require(file_hash(name) == expected, f"Generation source drift: {name}")
    for name, expected in receipt["artifact_hashes"].items():
        require(
            file_hash(directory / name) == expected,
            f"Artifact checksum mismatch: {name}",
        )
    roots = {}
    with (directory / "roots.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            world = p.world_from_dict(json.loads(line))
            require(world.id not in roots, "Duplicate root")
            p.validate_role_world(world)
            roots[world.id] = world.source
    require(len(roots) == receipt["roots"], "Root count mismatch")
    policy = json.loads((directory / "prefit-policy.json").read_bytes())
    require(
        policy["source_hashes"] == receipt["source_hashes"],
        "Prefit source binding mismatch",
    )
    expected_roots = {
        "population-"
        + source
        + "-"
        + "".join(map(str, incoming))
        + "-"
        + "".join(map(str, providers))
        + "-deposits-"
        + "".join("h" if c == "cash" else "b" for c in channels)
        for source, incoming, providers, channels in product(
            policy["sources"],
            policy["incoming"],
            policy["providers"],
            policy["patterns"],
        )
    }
    reused = json.loads((directory / "reused-roots.json").read_bytes())
    require(
        len(reused) == len(set(reused)) == receipt["reused_roots"],
        "Reused root roster mismatch",
    )
    require(
        not set(roots) & set(reused) and set(roots) | set(reused) == expected_roots,
        "Incomplete preregistered population",
    )
    vectors = json.loads((directory / "features.json").read_bytes())
    seen, counts, per_root = set(), Counter(), defaultdict(Counter)
    coverage = {
        axis: defaultdict(Counter)
        for axis in ("family", "profile", "channel", "verification")
    }
    conflicting = defaultdict(set)
    for sid, vector in vectors.items():
        require(set(vector) == set(FEATURE_NAMES), f"Feature roster mismatch: {sid}")
        require(
            all(
                (type(v) in (int, float) and math.isfinite(v))
                or (isinstance(v, str) and bool(v))
                for v in vector.values()
            ),
            f"Nonfinite feature: {sid}",
        )
    with (directory / "casebook.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            sid = row["scenario_id"]
            require(sid not in seen and sid in vectors, "Duplicate or missing scenario")
            seen.add(sid)
            check_economics(row)
            root = row["provenance"]["root_id"]
            # Coverage settlement worlds retain base identity through parent IDs.
            if root not in roots:
                parents = row["provenance"].get("parent_ids", [])
                matches = {
                    parent.removesuffix("-opaque-0").removesuffix("-opaque-1")
                    for parent in parents
                } & roots.keys()
                require(len(matches) == 1, "Missing base root ancestry")
                root = matches.pop()
            label = str(row["aml_label"])
            counts[label] += 1
            per_root[root][label] += 1
            behavior = row["public_snapshot"]["config"]["behavior"]
            cells = dict(
                family={row["family_id"]},
                profile={behavior["profile"]["id"]},
                channel={
                    s.get("action_details", {}).get("incoming_kind", s["card"]["code"])
                    for s in row["public_snapshot"]["steps"]
                },
                verification={
                    f["verification_status"] for f in behavior["aml_context"]["facts"]
                },
            )
            for axis, values in cells.items():
                for value in values:
                    coverage[axis][value][label] += 1
            counts["review:" + row["review_status"]] += 1
            conflicting[p.digest(vectors[sid])].add(label)
    require(
        seen == set(vectors) and len(seen) == receipt["rows"],
        "Scenario roster mismatch",
    )
    for root, source in roots.items():
        require(
            sum(per_root[root].values()) == (51 if source == "asset" else 39),
            "Per-root variant count mismatch",
        )
        require(
            abs(per_root[root]["0"] - per_root[root]["1"]) == 1,
            "Per-root class balance mismatch",
        )
    require(abs(counts["0"] - counts["1"]) <= 1, "Population class balance mismatch")
    report = dict(
        scope="saved-history-population-integrity-and-economic-consistency",
        rows=len(seen),
        roots=len(roots),
        standalone_components=receipt["components"],
        counts=dict(counts),
        coverage={
            a: {k: dict(v) for k, v in sorted(c.items())} for a, c in coverage.items()
        },
        conflicting_feature_vectors=sum(len(v) > 1 for v in conflicting.values()),
        source_receipt_sha256=file_hash(directory / "audit.json"),
        auditor_sha256=file_hash(__file__),
        all_artifact_hashes_verified=True,
        all_source_hashes_verified=True,
        all_saved_roots_economically_valid=True,
        all_saved_row_economics_consistent=True,
        engine_validation="Every row evaluated during source-bound generation; this is a separate saved-record consistency pass",
        independent_domain_review=False,
        release_ready=False,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(p.json_bytes(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--population", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.population, args.output)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "rows",
                    "roots",
                    "counts",
                    "standalone_components",
                    "release_ready",
                )
            }
        )
    )
