"""Export and independently recompute reviewed authored AML observations.

This module never authors labels, creates variants, or promotes an automated
check to domain review. Small or poorly separated inputs remain pilot artifacts.
"""

import csv
import hashlib
import io
import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

from scripts.aml_dataset.aml_labels import validate_label, validate_public
from scripts.aml_dataset.aml_provenance import connected_groups, digest
from scripts.aml_dataset.aml_review import verify_review_binding
from src.aml_workshop_simulator.core.expanded_game import expanded_game_config
from src.aml_workshop_simulator.domain.catalog import SEED_CARD_CATALOG
from src.aml_workshop_simulator.domain.game_models import card_spec_from_catalog
from src.aml_workshop_simulator.domain.round_policy import CARD_OVERRIDE_KEYS
from src.aml_workshop_simulator.domain.simulation import submit_blockers
from src.aml_workshop_simulator.schemas.round_config import AMLGameConfigOut
from src.aml_workshop_simulator.services.aml_context import evaluate
from src.aml_workshop_simulator.services.aml_dataset_features_v5 import (
    FEATURE_NAMES,
    extract_features,
)
from src.aml_workshop_simulator.services.semantic_contract import INCOMING_KINDS

SEED = 2026091601
VERSION = "aml-authored-dataset-v1"
SPLITS = {
    "train": 0.60,
    "validation": 0.15,
    "calibration-fit": 0.10,
    "calibration-check": 0.05,
    "test": 0.10,
}
CHALLENGES = {"masked-context", "unresolved", "new-combinations", "family-held-out"}
ROOT = Path(__file__).resolve().parents[2]


def check(condition, message):
    if not condition:
        raise ValueError(message)


def json_bytes(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def jsonl_bytes(rows):
    return "".join(
        json.dumps(r, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
        for r in rows
    ).encode("utf-8")


def csv_bytes(columns, rows):
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue().encode("utf-8")


def read_rows(path):
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def source_hashes():
    names = [
        "scripts/aml_dataset/aml_training.py",
        "scripts/aml_dataset/aml_provenance.py",
        "scripts/aml_dataset/aml_labels.py",
        "scripts/aml_dataset/aml_review.py",
        "src/aml_workshop_simulator/services/aml_context.py",
        "src/aml_workshop_simulator/services/aml_dataset_features_v5.py",
        "src/aml_workshop_simulator/services/aml_dataset_features_v4.py",
        "src/aml_workshop_simulator/services/aml_dataset_features_v3.py",
        "src/aml_workshop_simulator/services/aml_dataset_features_v2.py",
        "src/aml_workshop_simulator/services/aml_episodes.py",
        "src/aml_workshop_simulator/services/counterparties.py",
        "src/aml_workshop_simulator/schemas/aml_context.py",
        "src/aml_workshop_simulator/schemas/expanded_contract.py",
        "src/aml_workshop_simulator/schemas/round_config.py",
        "src/aml_workshop_simulator/schemas/scenarios.py",
        "src/aml_workshop_simulator/domain/game_models.py",
        "src/aml_workshop_simulator/services/semantic_contract.py",
        "src/aml_workshop_simulator/domain/simulation.py",
        "src/aml_workshop_simulator/domain/operation_timeline.py",
        "src/aml_workshop_simulator/domain/round_policy.py",
        "src/aml_workshop_simulator/domain/catalog.py",
        "src/aml_workshop_simulator/core/expanded_game.py",
        "config/base_round.json",
        "config/resource_rules.json",
        "config/operations.json",
        "config/parameters.json",
        "config/expanded_operations.json",
        "config/expanded_behavior.json",
    ]
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names
    }


def validate_sources(rows, protocol):
    check(protocol.get("version") == "aml-labels-v1", "Unsupported protocol")
    check(protocol.get("confirmed_class_prior") == 0.5, "Population prior must be 0.5")
    check(bool(rows), "Empty casebook")
    check(len({r["scenario_id"] for r in rows}) == len(rows), "Duplicate scenario ID")
    features = {}
    for row in rows:
        sid = row["scenario_id"]
        validate_label(row)
        verify_review_binding(row)
        public = row["public_snapshot"]
        validate_public(public)
        check(
            row["population_id"] == protocol["population_id"],
            f"Population mismatch: {sid}",
        )
        check(row["family_id"] in protocol["families"], f"Unsupported family: {sid}")
        check(
            row["label_protocol_version"] == protocol["version"],
            f"Protocol mismatch: {sid}",
        )
        if row["label_status"] == "confirmed":
            check(
                row["author_truth"].get("aml_episode_present")
                is bool(row["aml_label"]),
                f"Truth/label mismatch: {sid}",
            )
        config, steps = public["config"], public["steps"]
        check(
            config.get("schema_version") == 10, "Dataset requires actual v10 contract"
        )
        # Authored snapshots have cards but need not yet have an API config ID.
        AMLGameConfigOut.model_validate({"config_version": digest(config), **config})
        check(
            financial_projection(config) == fixed_financial_contract(),
            f"Changed fixed financial contract: {sid}",
        )
        check(
            not submit_blockers(evaluate(steps, config)),
            f"resource/objective blockers: {sid}",
        )
        result = extract_features(steps, config)
        check(list(result) == list(FEATURE_NAMES), "Feature allowlist/order mismatch")
        check(
            all(
                (type(v) in (int, float) and math.isfinite(v))
                or (isinstance(v, str) and bool(v))
                for v in result.values()
            ),
            f"Nonfinite or unsupported feature: {sid}",
        )
        features[sid] = result
    return features


def financial_projection(config):
    """Effective resources/constraints/cards; observation text and IDs are irrelevant."""
    ignored = {
        "id",
        "title",
        "description",
        "label",
        "help",
        "category",
        "default_visible_params",
        "risk_weight",
        "risk_points",
    }

    def normalize(value):
        if isinstance(value, dict):
            if "value" in value:
                value = {"energy_cost": 0, "time_cost": 0, **value}
            if "key" in value and "kind" in value:
                value = {"required": True, **value}
            return {k: normalize(v) for k, v in value.items() if k not in ignored}
        if isinstance(value, (list, tuple)):
            return [normalize(v) for v in value]
        if type(value) in (int, float, Decimal) or isinstance(value, str):
            try:
                return str(Decimal(str(value)).normalize())
            except InvalidOperation:
                return value
        return value

    cards = {(c["code"], c["version"]): c for c in config["card_snapshots"]}
    check(
        len(cards) == len(config["card_snapshots"]),
        "Duplicate cards in financial contract",
    )
    operations = {}
    for operation in config["operations"]:
        key = (operation["code"], operation["version"])
        check(key in cards, "Missing card in financial contract")
        effective = {
            **cards[key],
            **{
                k: operation[k]
                for k in CARD_OVERRIDE_KEYS
                if operation.get(k) is not None
            },
        }
        operations[f"{key[0]}:{key[1]}"] = normalize(effective)
    return {
        **{
            key: normalize(config[key])
            for key in (
                "resources",
                "objectives",
                "constraints",
                "resource_rules",
                "ruleset_version",
            )
        },
        "cards": operations,
        "turnover": normalize(config["behavior"]["turnover"]),
        "purchases": normalize(config["behavior"].get("purchases")),
        "snapshot_card_keys": sorted(f"{k[0]}:{k[1]}" for k in cards),
    }


@lru_cache(maxsize=1)
def fixed_financial_contract():
    reference = expanded_game_config(
        datetime.fromisoformat("2026-09-13T09:00:00+03:00")
    )
    reference["card_snapshots"] = [
        asdict(card_spec_from_catalog(card, i))
        for i, card in enumerate(SEED_CARD_CATALOG, 1)
    ]
    return financial_projection(reference)


def apportioned(total):
    counts = {name: math.floor(total * weight) for name, weight in SPLITS.items()}
    ordered = sorted(
        SPLITS,
        key=lambda name: (
            -(total * SPLITS[name] - counts[name]),
            list(SPLITS).index(name),
        ),
    )
    for name in ordered[: total - sum(counts.values())]:
        counts[name] += 1
    return counts


def split_groups(groups, rows_by_id):
    """Stratify by component label counts; largest remainder per stratum.

    Mixed-label connected components stay intact. Balance is audited rather than
    fabricated by splitting a component or silently dropping difficult labels.
    """
    strata = defaultdict(list)
    for gid, ids in groups.items():
        counts = Counter(rows_by_id[sid]["aml_label"] for sid in ids)
        strata[(counts[0], counts[1])].append(gid)
    assignment = {}
    rng = random.Random(SEED)
    for key in sorted(strata):
        pool = sorted(strata[key])
        rng.shuffle(pool)
        quotas = apportioned(len(pool))
        offset = 0
        for name, count in quotas.items():
            for gid in pool[offset : offset + count]:
                assignment[gid] = name
            offset += count
    return assignment


def coverage_report(rows, protocol):
    axes = {
        "family": defaultdict(Counter),
        "profile": defaultdict(Counter),
        "channel": defaultdict(Counter),
        "verification": defaultdict(Counter),
    }
    for family in set(protocol["families"]) - set(protocol.get("family_held_out", [])):
        axes["family"][family] = Counter()
    for channel in INCOMING_KINDS:
        axes["channel"][channel] = Counter()
    for row in rows:
        config, steps = (
            row["public_snapshot"]["config"],
            row["public_snapshot"]["steps"],
        )
        label = str(row["aml_label"])
        axes["family"][row["family_id"]][label] += 1
        profile = config["behavior"]["profile"]
        profile_key = profile.get("id", profile.get("title", "unknown"))
        axes["profile"][profile_key][label] += 1
        for channel in {
            s.get("action_details", {}).get("incoming_kind", s["card"]["code"])
            for s in steps
        }:
            axes["channel"][channel][label] += 1
        for status in {
            f["verification_status"] for f in config["behavior"]["aml_context"]["facts"]
        }:
            axes["verification"][status][label] += 1
    result = {
        axis: {
            key: {
                "class_0": value["0"],
                "class_1": value["1"],
                "both_classes": bool(value["0"] and value["1"]),
            }
            for key, value in sorted(cells.items())
        }
        for axis, cells in axes.items()
    }
    result["missing_cells"] = [
        {
            "axis": axis,
            "cell": key,
            "status": "not_observed; feasibility not established",
        }
        for axis, cells in result.items()
        for key, value in cells.items()
        if not value["both_classes"]
    ]
    return result


def derive(rows, protocol):
    rows = sorted(rows, key=lambda r: r["scenario_id"])
    by_id = {r["scenario_id"]: r for r in rows}
    features = validate_sources(rows, protocol)
    provenance = connected_groups(rows, features)
    mapping = provenance["scenario_groups"]
    eligible = {
        r["scenario_id"]
        for r in rows
        if r["review_status"] == "reviewed"
        and r["label_status"] == "confirmed"
        and r.get("challenge_set") not in {"masked-context", "unresolved"}
    }
    challenges, excluded, main_groups = {}, [], {}
    family_holdout = set(protocol.get("family_held_out", []))
    check(
        family_holdout <= set(protocol["families"]),
        "Unknown preregistered held-out family",
    )
    combination_holdout = set(protocol.get("new_combination_scenarios", []))
    check(
        combination_holdout <= set(by_id),
        "Unknown preregistered new-combination scenario",
    )
    for gid, ids in provenance["groups"].items():
        destinations = set()
        for sid in ids:
            row = by_id[sid]
            destination = row.get("challenge_set")
            if destination == "family-held-out":
                check(
                    row["family_id"] in family_holdout,
                    "Family-held-out tag requires preregistered protocol family",
                )
            if destination == "new-combinations":
                check(
                    sid in combination_holdout,
                    "New-combinations tag requires preregistered protocol scenario",
                )
            if row["family_id"] in family_holdout:
                destination = "family-held-out"
            elif sid in combination_holdout:
                destination = "new-combinations"
            if destination is not None:
                check(destination in CHALLENGES, "Unknown challenge_set")
                if destination in {"family-held-out", "new-combinations"}:
                    destinations.add(destination)
        if destinations:
            # A component cannot contaminate main train/test or another challenge.
            destination = (
                "family-held-out"
                if "family-held-out" in destinations
                else sorted(destinations)[0]
            )
            challenges[gid] = destination
        else:
            accepted = [sid for sid in ids if sid in eligible]
            if accepted:
                main_groups[gid] = accepted
    assigned = split_groups(main_groups, by_id)
    scenarios, split_rows, challenge_rows, diagnostic_rows = (
        [],
        [],
        defaultdict(list),
        defaultdict(list),
    )
    for row in rows:
        sid, gid = row["scenario_id"], mapping[row["scenario_id"]]
        if gid in challenges:
            if row["review_status"] == "rejected":
                excluded.append(
                    {"scenario_id": sid, "reason": "rejected", "group_id": gid}
                )
            else:
                challenge_rows[challenges[gid]].append(
                    {
                        **row,
                        "group_id": gid,
                        "split": "challenge:" + challenges[gid],
                        "features": features[sid],
                    }
                )
        elif row["review_status"] != "rejected" and (
            row["label_status"] == "unresolved"
            or row.get("challenge_set") in {"unresolved", "masked-context"}
        ):
            destination = row.get("challenge_set") or "unresolved"
            diagnostic_rows[destination].append(
                {
                    **row,
                    "group_id": gid,
                    "split": "diagnostic:" + destination,
                    "parent_split": assigned.get(gid),
                    "independent": False,
                    "evaluation_scope": "non-independent diagnostic; never pooled with main test",
                    "features": features[sid],
                }
            )
        elif sid in eligible:
            record = {
                **row,
                "group_id": gid,
                "split": assigned[gid],
                "features": features[sid],
            }
            scenarios.append(record)
            split_rows.append(
                {
                    "scenario_id": sid,
                    "group_id": gid,
                    "split": assigned[gid],
                    "aml_label": row["aml_label"],
                }
            )
        else:
            excluded.append(
                {"scenario_id": sid, "reason": row["review_status"], "group_id": gid}
            )
    coverage = coverage_report(scenarios, protocol)
    collisions = defaultdict(list)
    for row in rows:
        collisions[digest(features[row["scenario_id"]])].append(row["scenario_id"])
    conflicts = [
        {
            "feature_sha256": key,
            "scenario_ids": ids,
            "labels": sorted(
                {
                    by_id[sid]["aml_label"]
                    for sid in ids
                    if by_id[sid]["aml_label"] is not None
                }
            ),
            "group_id": mapping[ids[0]],
        }
        for key, ids in sorted(collisions.items())
        if len(
            {
                by_id[sid]["aml_label"]
                for sid in ids
                if by_id[sid]["aml_label"] is not None
            }
        )
        > 1
    ]
    split_counts = {}
    unmet = []
    if any(not verify_review_binding(row) for row in rows if row["review_status"] == "reviewed"):
        unmet.append("independent_review_binding")
    if any(row["review_status"] != "reviewed"
           for records in challenge_rows.values() for row in records):
        unmet.append("independent_challenge_review")
    if any(row["review_status"] != "reviewed"
           for records in diagnostic_rows.values() for row in records):
        unmet.append("independent_diagnostic_review")
    if len(scenarios) < 30000:
        unmet.append("minimum_confirmed_rows")
    if len(main_groups) < 1200:
        unmet.append("minimum_independent_groups")
    sizes = {len(ids) for ids in main_groups.values()}
    if len(sizes) != 1:
        unmet.append("equal_variants_per_group")
    global_counts = Counter(row["aml_label"] for row in scenarios)
    tolerance = max(sizes, default=0)
    if (
        not all(global_counts[c] for c in (0, 1))
        or abs(global_counts[0] - global_counts[1]) > tolerance
    ):
        unmet.append("balanced_population")
    for name in SPLITS:
        selected = [r for r in scenarios if r["split"] == name]
        counts = Counter(r["aml_label"] for r in selected)
        gids = {r["group_id"] for r in selected}
        group_classes = {
            c: sum(
                any(by_id[sid]["aml_label"] == c for sid in main_groups[gid])
                for gid in gids
            )
            for c in (0, 1)
        }
        split_counts[name] = {
            "rows": len(selected),
            "groups": len(gids),
            "class_0": counts[0],
            "class_1": counts[1],
            "groups_with_class_0": group_classes[0],
            "groups_with_class_1": group_classes[1],
        }
        if (
            not all(counts[c] for c in (0, 1))
            or abs(counts[0] - counts[1]) > tolerance
            or abs(group_classes[0] - group_classes[1]) > 1
        ):
            unmet.append("split_balance:" + name)
        if abs(len(gids) - len(main_groups) * SPLITS[name]) > 1:
            unmet.append("split_allocation:" + name)
    if coverage["missing_cells"]:
        unmet.append("coverage_both_classes")
    for name in ("masked-context", "new-combinations", "family-held-out"):
        if not (diagnostic_rows if name == "masked-context" else challenge_rows).get(
            name
        ):
            unmet.append("challenge_missing:" + name)
    report = {
        "status": "not-release-ready" if unmet else "release-ready",
        "release_ready": not unmet,
        "source_rows": len(rows),
        "confirmed_rows": len(scenarios),
        "groups": len(main_groups),
        "all_connected_groups": len(provenance["groups"]),
        "excluded_rows": len(excluded),
        "challenge_rows": {k: len(v) for k, v in sorted(challenge_rows.items())},
        "diagnostic_rows": {k: len(v) for k, v in sorted(diagnostic_rows.items())},
        "feature_count": len(FEATURE_NAMES),
        "conflicting_feature_groups": len(conflicts),
        "split_counts": split_counts,
        "unmet_gates": unmet,
    }
    artifacts = {
        "scenarios.jsonl": jsonl_bytes(scenarios),
        "features.csv": csv_bytes(
            ["scenario_id", *FEATURE_NAMES],
            [{"scenario_id": r["scenario_id"], **r["features"]} for r in scenarios],
        ),
        "split.csv": csv_bytes(
            ["scenario_id", "group_id", "split", "aml_label"], split_rows
        ),
        "groups.json": json_bytes(provenance),
        "coverage.json": json_bytes(coverage),
        "collisions.json": json_bytes(
            {
                "conflicting_labels": conflicts,
                "duplicate_feature_groups": sum(
                    len(ids) > 1 for ids in collisions.values()
                ),
            }
        ),
        "excluded.json": json_bytes(excluded),
        "audit.json": json_bytes(report),
        "feature-schema.json": json_bytes(
            {
                "version": "aml-observable-v5.0",
                "features": list(FEATURE_NAMES),
                "types": {
                    name: "categorical"
                    if isinstance(features[rows[0]["scenario_id"]][name], str)
                    else "numeric"
                    for name in FEATURE_NAMES
                },
            }
        ),
    }
    for name, records in challenge_rows.items():
        artifacts[f"challenges/{name}.jsonl"] = jsonl_bytes(records)
    for name, records in diagnostic_rows.items():
        artifacts[f"diagnostics/{name}.jsonl"] = jsonl_bytes(records)
    return artifacts, report


def make_manifest(rows, protocol, artifacts, report):
    return {
        "version": VERSION,
        "seed": SEED,
        "population_id": protocol["population_id"],
        "confirmed_class_prior": 0.5,
        "protocol_sha256": digest(protocol),
        "casebook_sha256": digest(rows),
        "feature_names": list(FEATURE_NAMES),
        "source_hashes": source_hashes(),
        "financial_contract_sha256": digest(fixed_financial_contract()),
        "split_weights": SPLITS,
        "stratification": "connected-component label-count strata; seeded shuffle; largest remainder; fixed split-order tie break",
        "challenge_policy": "Only preregistered family-held-out/new-combinations reserve whole components. Unresolved/masked siblings are non-independent diagnostics with parent group/split; confirmed siblings remain supervised.",
        "status": report["status"],
        "release_ready": report["release_ready"],
        "artifact_hashes": {
            name: hashlib.sha256(data).hexdigest()
            for name, data in sorted(artifacts.items())
        },
    }


def build_dataset(casebook: Path, protocol: Path, output: Path) -> None:
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"Refusing existing output: {output}")
    rows = read_rows(casebook)
    rules = json.loads(Path(protocol).read_text(encoding="utf-8"))
    artifacts, report = derive(rows, rules)
    artifacts["casebook.jsonl"] = jsonl_bytes(rows)
    artifacts["protocol.json"] = json_bytes(rules)
    manifest = make_manifest(rows, rules, artifacts, report)
    output.mkdir(parents=True, exist_ok=False)
    for name, content in artifacts.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (output / "manifest.json").write_bytes(json_bytes(manifest))


def audit_dataset(directory: Path) -> dict:
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    check(manifest.get("version") == VERSION, "Unsupported dataset version")
    for name, expected in manifest["artifact_hashes"].items():
        path = directory / name
        check(
            path.resolve().is_relative_to(directory.resolve()), "Unsafe artifact path"
        )
        check(
            path.is_file()
            and hashlib.sha256(path.read_bytes()).hexdigest() == expected,
            f"Artifact checksum mismatch: {name}",
        )
    rows = read_rows(directory / "casebook.jsonl")
    protocol = json.loads((directory / "protocol.json").read_text(encoding="utf-8"))
    artifacts, report = derive(rows, protocol)
    artifacts["casebook.jsonl"] = jsonl_bytes(rows)
    artifacts["protocol.json"] = json_bytes(protocol)
    for name, expected in artifacts.items():
        check(
            (directory / name).is_file()
            and (directory / name).read_bytes() == expected,
            f"Recomputation mismatch (group/split/features/source): {name}",
        )
    expected_manifest = make_manifest(rows, protocol, artifacts, report)
    check(
        manifest == expected_manifest,
        "Manifest/source checksum or release status mismatch",
    )
    actual_files = {
        p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()
    }
    check(
        actual_files == {*artifacts, "manifest.json"},
        "Unexpected or unmanifested dataset artifacts",
    )
    return report
