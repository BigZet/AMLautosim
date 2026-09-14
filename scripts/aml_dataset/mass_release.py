"""Gated pilot/release exports. Calling this module never grants human approval."""

import csv
import json
import math
import random
from copy import deepcopy
from pathlib import Path

from scripts.aml_dataset.expanded import (
    digest,
    stable,
    record,
    valid,
    rubric,
    fingerprint,
    GENERATOR_VERSION,
)
from scripts.aml_dataset.joint_review import check_joint_review, check_decisions
from src.aml_workshop_simulator.services.aml_dataset_features_v2 import (
    extract_features,
    FEATURE_VERSION,
)
from src.aml_workshop_simulator.services.expanded_simulation import (
    evaluate_expanded_scenario,
)

SPLITS = {
    "five-transfers": "train",
    "six-transfers": "validation",
    "eight-transfers": "test",
}


def read_json(path):
    return json.loads(path.read_text())


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def check_projected_labels(rows, columns):
    """The exported model vector must not conceal conflicting rubric labels."""
    labels = {}
    for row in rows:
        key = digest({column: row["features"][column] for column in columns})
        target = row["target_risk_score"]
        if key in labels and labels[key] != target:
            raise ValueError("Conflicting labels after feature projection")
        labels[key] = target


def candidates(references, count, seed, diagnostic_sink=None):
    """Bounded diversity sampling, no ranking/filtering by risk score."""
    rng = random.Random(seed)
    accepted = []
    seen = set()
    rejected = 0
    for attempt in range(count * 40):
        parent = references[attempt % len(references)]
        config = parent["config_snapshot"]
        steps = deepcopy(parent["steps"])
        for step in steps:
            code = step["card"]["code"]
            if code == "incoming_transfer":
                step["sender_id"] = rng.choice(["A", "B", "C", "D"])
                step["action_details"]["transfer_source"] = rng.choice(
                    [
                        "domestic_bank",
                        "payment_service",
                        "crypto_exchange",
                        "foreign_bank_kg",
                    ]
                )
            if code == "card_transfer":
                step["recipient_id"] = rng.choice(["A", "B", "C", "D"])
                step["context"]["channel"] = rng.choice(["mobile", "web", "branch"])
            if step.get("interval_minutes") is not None:
                step["interval_minutes"] = rng.choices(
                    [1, 10, 60, 1440], [80, 10, 8, 2]
                )[0]
        if not valid(steps, config):
            rejected += 1
            if diagnostic_sink is not None:
                from src.aml_workshop_simulator.domain.simulation import submit_blockers

                diagnostic_sink(
                    dict(
                        attempt=attempt,
                        parent_id=parent["id"],
                        config_hash=digest(config),
                        steps=steps,
                        blockers=submit_blockers(
                            evaluate_expanded_scenario(steps, config)
                        ),
                    )
                )
            continue
        observable = fingerprint(steps, config)
        if observable in seen:
            continue
        seen.add(observable)
        accepted.append(
            record(
                f"D{len(accepted) + 1:05}",
                steps,
                config,
                parent["family"],
                parent["group"],
            )
        )
        if len(accepted) == count:
            break
    return accepted, rejected


def review_sample(rows, counts=(60, 30, 30)):
    if len(rows) < sum(counts):
        raise ValueError("Pilot needs enough unique cases for review")
    ordered = sorted(rows, key=lambda r: (r["target_risk_score"], r["id"]))
    picked = []
    used = set()
    for i in range(counts[0]):
        row = ordered[round(i * (len(ordered) - 1) / (counts[0] - 1))]
        picked.append({"reason": "risk_range", "record": row})
        used.add(row["id"])
    for (reason, key), limit in zip([
        (
            "boundary",
            lambda r: min(abs(r["target_risk_score"] - a) for a in (25, 50, 75)),
        ),
        (
            "baseline_disagreement",
            lambda r: -abs(r["target_risk_score"] - float(r["baseline"]["risk_score"])),
        ),
    ], counts[1:]):
        options = sorted(
            (r for r in rows if r["id"] not in used), key=lambda r: (key(r), r["id"])
        )[:limit]
        picked += [{"reason": reason, "record": r} for r in options]
        used.update(r["id"] for r in options)
    return picked


def review_contract(directory):
    """An explicit per-pilot policy preserves old review artifacts and gates."""
    path = Path(directory) / "review-policy.json"
    if not path.exists():
        return dict(sample="review120.jsonl", decisions="pilot-decisions.csv",
                    decision="pilot-decision.json", blind=True, counts=(60, 30, 30))
    policy = read_json(path)
    if policy.get("version") != "human-12-no-blind-v1" or not policy.get("user_evidence"):
        raise ValueError("Unknown or undocumented review policy")
    return dict(sample="review12.jsonl", decisions="pilot-decisions-short.csv",
                decision="pilot-decision-short.json", blind=False, counts=(4, 4, 4))


def validate_mass(directory):
    directory = Path(directory)
    manifest = read_json(directory / "manifest.json")
    rows = read_rows(directory / "scenarios.jsonl")
    if manifest["stage"] not in ("pilot", "release") or manifest["rows_hash"] != digest(
        rows
    ):
        raise ValueError("Invalid stage or changed dataset")
    if manifest["extractor"] != FEATURE_VERSION or manifest["rubric_hash"] != digest(
        rubric()
    ):
        raise ValueError("Version mismatch")
    if (
        manifest["generator"] != GENERATOR_VERSION
        or digest(read_json(directory / "rubric.json")) != manifest["rubric_hash"]
    ):
        raise ValueError("Changed generator or rubric snapshot")
    if len(rows) != manifest["count"] or not rows:
        raise ValueError("Incorrect dataset size")
    from scripts.aml_dataset.expanded import label

    hashes = set()
    for row in rows:
        config = row["config_snapshot"]
        if not valid(row["steps"], config) or digest(config) != row["config_hash"]:
            raise ValueError("Invalid scenario snapshot")
        if (
            row["observable_hash"] != fingerprint(row["steps"], config)
            or row["observable_hash"] in hashes
        ):
            raise ValueError("Duplicate/changed observable scenario")
        hashes.add(row["observable_hash"])
        if row["features"] != extract_features(row["steps"], config):
            raise ValueError("Changed features")
        if row["target_risk_score"] != label(row["features"], rubric())[0]:
            raise ValueError("Changed label")
        snapshot = evaluate_expanded_scenario(row["steps"], config)
        if (
            row["resources"] != snapshot["resources_after"]
            or row["totals"] != snapshot["totals"]
        ):
            raise ValueError("Changed resource calculation")
        if (
            row["group"]
            != {5: "five-transfers", 6: "six-transfers", 8: "eight-transfers"}[
                row["features"]["count_card_transfer"]
            ]
        ):
            raise ValueError("Incorrect lineage")
        if any(
            not isinstance(v, str) and not math.isfinite(v)
            for v in row["features"].values()
        ):
            raise ValueError("Nonfinite feature")
    with (directory / "split.csv").open() as file:
        partitions = list(csv.DictReader(file))
    schema = read_json(directory / "feature-schema.json")
    training = [r for r in rows if SPLITS[r["group"]] == "train"]
    if not training:
        raise ValueError("No training parents")
    columns = sorted(
        k
        for k in training[0]["features"]
        if len({r["features"][k] for r in training}) > 1
    )
    if columns != schema["columns"]:
        raise ValueError("Feature schema must use training parents only")
    check_projected_labels(rows, columns)
    with (directory / "features.csv").open() as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != columns + ["target_risk_score"]:
            raise ValueError("Unexpected model input columns")
        features = list(reader)
    if len(partitions) != len(rows) or len(features) != len(rows):
        raise ValueError("Incorrect export length")
    for i, (row, partition, feature) in enumerate(zip(rows, partitions, features)):
        if partition != {
            "row_index": str(i),
            "id": row["id"],
            "group": row["group"],
            "split": SPLITS[row["group"]],
        }:
            raise ValueError("Split conflict")
        expected = {k: str(row["features"][k]) for k in columns}
        expected["target_risk_score"] = str(row["target_risk_score"])
        if feature != expected:
            raise ValueError("CSV mismatch")
    if manifest["stage"] == "pilot":
        if read_rows(directory / "review120.jsonl") != review_sample(rows):
            raise ValueError("Changed pilot review sample")
        contract = review_contract(directory)
        if contract["sample"] != "review120.jsonl":
            if read_rows(directory / contract["sample"]) != review_sample(rows, contract["counts"]):
                raise ValueError("Changed short pilot review sample")
    from src.aml_workshop_simulator.domain.simulation import submit_blockers

    configurations = read_json(directory / "configurations.json")
    with (directory / "diagnostics.jsonl").open() as file:
        for line in file:
            diagnostic = json.loads(line)
            config = configurations[diagnostic["config_hash"]]
            if (
                digest(config) != diagnostic["config_hash"]
                or not diagnostic["blockers"]
                or diagnostic["blockers"]
                != submit_blockers(
                    evaluate_expanded_scenario(diagnostic["steps"], config)
                )
            ):
                raise ValueError("Changed diagnostic scenario")
    return {
        "count": len(rows),
        "status": "technical_checks_passed",
        "joint_review_verified_by_this_validator": False,
    }


def verify_pilot_review(pilot, reference_manifest, seed):
    from datetime import datetime

    validate_mass(pilot)
    manifest = read_json(pilot / "manifest.json")
    contract = review_contract(pilot)
    decision = read_json(pilot / contract["decision"])
    if manifest["stage"] != "pilot" or manifest["count"] != 2000:
        raise ValueError("A 2000-row pilot is required")
    if (
        manifest["reference_package_hash"] != reference_manifest["package_hash"]
        or manifest["seed"] != seed
    ):
        raise ValueError("Release must use the reviewed pilot references and seed")
    if (
        decision.get("pilot_rows_hash") != manifest["rows_hash"]
        or decision.get("status") != "approved"
    ):
        raise ValueError("Joint pilot review is pending or stale")
    if (
        not decision.get("reviewer", "").strip()
        or not decision.get("user_decision_evidence", "").strip()
    ):
        raise ValueError("Explicit pilot review evidence is required")
    if datetime.fromisoformat(decision["reviewed_at"]).tzinfo is None:
        raise ValueError("Review time requires timezone")
    sample = read_rows(pilot / contract["sample"])
    if not contract["blind"] and decision.get("sample_hash") != digest(sample):
        raise ValueError("Short review belongs to another sample")
    check_decisions(pilot, [r["record"] for r in sample], contract["decisions"])


def generate_mass(reference_dir, destination, stage, seed=20260914, pilot_dir=None):
    from scripts.aml_dataset.joint_review import FIELDS

    reference_dir = Path(reference_dir)
    destination = Path(destination)
    if stage not in ("pilot", "release"):
        raise ValueError("Only pilot or release supported")
    # All gates precede sampling, labeling and output creation.
    require_blind = stage == "release" and (
        pilot_dir is None or review_contract(pilot_dir)["blind"]
    )
    check_joint_review(reference_dir, require_blind=require_blind)
    reference_manifest = read_json(reference_dir / "manifest.json")
    if stage == "release":
        if pilot_dir is None:
            raise ValueError("Reviewed pilot required before release")
        verify_pilot_review(Path(pilot_dir), reference_manifest, seed)
    if destination.exists():
        raise FileExistsError(destination)
    references = read_rows(reference_dir / "references.jsonl")
    count = 2000 if stage == "pilot" else 20000
    destination.mkdir(parents=True)
    (destination / "generation-status.json").write_text(
        json.dumps({"status": "running", "stage": stage})
    )
    configurations = {r["config_hash"]: r["config_snapshot"] for r in references}
    (destination / "configurations.json").write_text(
        json.dumps(configurations, ensure_ascii=False)
    )
    with (destination / "diagnostics.jsonl").open("w") as file:
        rows, rejected = candidates(
            references, count, seed, lambda row: file.write(stable(row) + "\n")
        )
    if stage == "pilot" and len(rows) != 2000 or not rows:
        (destination / "generation-status.json").write_text(
            json.dumps({"status": "insufficient_diversity", "count": len(rows)})
        )
        raise ValueError("Insufficient unique valid scenarios; no duplicate padding")

    def write(name, value):
        (destination / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        )

    manifest = dict(
        stage=stage,
        generator=GENERATOR_VERSION,
        extractor=FEATURE_VERSION,
        seed=seed,
        count=len(rows),
        requested=count,
        rows_hash=digest(rows),
        rubric_hash=digest(rubric()),
        reference_package_hash=reference_manifest["package_hash"],
    )
    write("manifest.json", manifest)
    write("rubric.json", rubric())
    (destination / "scenarios.jsonl").write_text(
        "".join(stable(r) + "\n" for r in rows)
    )
    training = [r for r in rows if SPLITS[r["group"]] == "train"]
    columns = sorted(
        k for k in rows[0]["features"] if len({r["features"][k] for r in training}) > 1
    )
    write("feature-schema.json", {"version": FEATURE_VERSION, "columns": columns})
    with (destination / "features.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns + ["target_risk_score"])
        writer.writeheader()
        writer.writerows(
            {
                **{k: r["features"][k] for k in columns},
                "target_risk_score": r["target_risk_score"],
            }
            for r in rows
        )
    with (destination / "split.csv").open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["row_index", "id", "group", "split"])
        writer.writerows(
            [i, r["id"], r["group"], SPLITS[r["group"]]] for i, r in enumerate(rows)
        )
    if stage == "pilot":
        sample = review_sample(rows)
        (destination / "review120.jsonl").write_text(
            "".join(stable(r) + "\n" for r in sample)
        )
        with (destination / "pilot-decisions.csv").open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(
                {
                    "id": r["record"]["id"],
                    "observable_hash": r["record"]["observable_hash"],
                }
                for r in sample
            )
        write(
            "pilot-decision.json",
            dict(
                status="pending",
                pilot_rows_hash=manifest["rows_hash"],
                reviewer="",
                reviewed_at="",
                user_decision_evidence="",
            ),
        )
    report = validate_mass(destination)
    report.update(
        rejected_candidates=rejected,
        shortfall=count - len(rows),
        groups=len({r["group"] for r in rows}),
        risk_range=[
            min(r["target_risk_score"] for r in rows),
            max(r["target_risk_score"] for r in rows),
        ],
    )
    write("quality.json", report)
    write(
        "generation-status.json",
        {"status": "technical_checks_passed", "joint_review_pending": stage == "pilot"},
    )
    (destination / "DATASET_CARD.md").write_text(f"""# Учебный AML-датасет {stage}

Размер: {len(rows)} из запрошенных {count}; недобор: {count - len(rows)}. Допустимые дубликаты не добавляются.
Снимок каждого синтетического раунда находится в config_snapshot соответствующей записи.
Рубрика: {rubric()["version"]}; extractor: {FEATURE_VERSION}; seed: {seed}.
Служебные поля и baseline находятся вне CSV модели. Разбиение фиксировано по родителям;
константы исключены по обучающей части. Предыстория не расходует ресурсы цепочки.

Ограничения: всего три группы родителей в основной выборке. Расширение численности не
создаёт независимые семейства поведения. Слепая группа с семью переводами хранится в
пакете кандидатов и не используется для подбора признаков или рубрики. Результаты не
подтверждают эффективность реального банковского AML. CatBoost не обучался.

Объём ручной проверки определяется review-policy.json пилота. По текущему решению
пользователя проверяются 12 случаев с расчётными баллами, без обязательной слепой оценки.
Архивные пилоты без файла политики сохраняют прежний порядок 120+24.
Проверка файлов сама по себе не является ручным разбором.
""")
    if stage == "pilot":
        from scripts.prepare_short_aml_review import prepare
        prepare(destination)
    return report
