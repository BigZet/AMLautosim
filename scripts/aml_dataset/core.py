"""Deterministic generation, independent rubric, and auditable export."""

import csv
import hashlib
import json
import random
import uuid
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from src.aml_workshop_simulator.core.game_config import base_game_config
from src.aml_workshop_simulator.domain.catalog import CARD_CATALOG
from src.aml_workshop_simulator.domain.round_policy import RoundPolicy
from src.aml_workshop_simulator.domain.rules import (
    card_spec_from_catalog,
    evaluate_scenario,
    submit_blockers,
)
from src.aml_workshop_simulator.domain.scoring import score_scenario
from src.aml_workshop_simulator.schemas.scenarios import ScenarioStepIn
from src.aml_workshop_simulator.services.aml_dataset_features import (
    CATEGORICAL_FEATURES,
    FEATURE_VERSION,
    extract_features,
)
from src.aml_workshop_simulator.services.configuration import snapshot_specs
from src.aml_workshop_simulator.services.scenario_service import canonical_steps

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/synthetic_dataset"


def read_json(path):
    return json.loads(Path(path).read_text())


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def write_json(path, value):
    Path(path).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )


def write_jsonl(path, rows):
    Path(path).write_text(
        "".join(
            json.dumps(r, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
            for r in rows
        )
    )


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line]


def write_csv(path, rows, fields):
    with Path(path).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def frozen_config():
    config = base_game_config()
    config["card_snapshots"] = json.loads(
        json.dumps(
            [
                asdict(card_spec_from_catalog(entry, i))
                for i, entry in enumerate(CARD_CATALOG, 1)
            ],
            default=str,
        )
    )
    return config


def content_hash(steps):
    return digest([{k: v for k, v in s.items() if k != "step_id"} for s in steps])


def label(features, rubric):
    contributions = []
    for term in rubric["terms"]:
        value = features[term["feature"]]
        if "multiply_by" in term:
            value *= features[term["multiply_by"]]
        points = value * term["weight"]
        contributions.append(
            {
                "reason": term["reason"],
                "feature": term["feature"],
                "points": round(points, 6),
            }
        )
    return round(
        min(100, max(0, sum(c["points"] for c in contributions))), 2
    ), contributions


def normalize(raw, config):
    specs = snapshot_specs(config)
    by_code = {s.code: s for s in specs.values()}
    inputs = []
    for i, step in enumerate(raw):
        spec = by_code[step["code"]]
        inputs.append(
            ScenarioStepIn.model_validate(
                {
                    "step_id": str(
                        uuid.uuid5(uuid.NAMESPACE_URL, f"aml-v1:{digest(raw)}:{i}")
                    ),
                    "card": {"id": spec.id, "code": spec.code, "version": spec.version},
                    "amount": str(step["amount"]),
                    "context": step.get("context", {}),
                    "action_details": {
                        **{f["key"]: f["default"] for f in spec.fields},
                        **step.get("details", {}),
                    },
                }
            )
        )
    return json.loads(
        json.dumps(
            canonical_steps(inputs, specs, RoundPolicy.from_config(config, specs))
        )
    )


def make_record(steps, config, rubric, family, template_id):
    features = extract_features(steps, config)
    score, reasons = label(features, rubric)
    snapshot = evaluate_scenario(steps, snapshot_specs(config), config)
    return {
        "scenario_id": content_hash(steps),
        "template_id": template_id,
        "family": family,
        "config_hash": digest(config),
        "steps": steps,
        "features": features,
        "target_risk_score": score,
        "reasons": reasons,
        "label_source": "synthetic_rubric",
        "label_version": rubric["version"],
        "review_status": "pending",
        "label_confidence": None,
        "baseline_risk_score": float(
            score_scenario(steps, snapshot_specs(config), config)["risk_score"]
        ),
        "evaluation": {
            "can_submit": not submit_blockers(snapshot),
            "blockers": submit_blockers(snapshot),
            "resources_after": snapshot["resources_after"],
            "totals": snapshot["totals"],
        },
    }


def candidate(rng, family, config, variant):
    """Sample observable motifs; engine rejection is the final feasibility authority.

    Search distributions are explicit v1 design choices for the current game,
    not empirical transaction distributions or AML reporting thresholds.
    """
    specs = {s.code: s for s in snapshot_specs(config).values()}
    salary = rng.random() < 0.3
    salary_anchor = family == "ordinary" and variant in (0, 2, 4)
    salary = salary or salary_anchor
    raw = []
    if salary:
        raw.append(
            {
                "code": "salary",
                "amount": rng.randint(
                    int(specs["salary"].min_amount), int(specs["salary"].max_amount)
                ),
                "details": {
                    "income_basis": rng.choice(
                        ["payroll_registry", "service_contract", "no_reference"]
                    )
                },
            }
        )
    target = int(float(config["objectives"]["target_outflow"])) + rng.randint(0, 7000)
    # Incoming range follows the funding need, including a commission margin.
    required = (
        target
        + 7000
        - int(float(config["resources"]["initial_balance"]))
        - sum(s["amount"] for s in raw)
    )
    incoming_min = max(int(specs["incoming_transfer"].min_amount), (required + 2) // 3)
    incoming_max = int(specs["incoming_transfer"].max_amount)
    if incoming_min > incoming_max:
        raise ValueError("Current generation profile cannot fund this round")
    for _ in range(3):
        raw.append(
            {
                "code": "incoming_transfer",
                "amount": rng.randint(incoming_min, incoming_max),
                "details": {
                    "transfer_source": rng.choice(
                        [
                            "domestic_bank",
                            "foreign_bank_kg",
                            "crypto_exchange",
                            "payment_service",
                        ]
                    ),
                    "sender_relationship": rng.choice(
                        ["regular_sender"] * (4 if variant % 2 == 0 else 1)
                        + ["anonymous_new_account", "anonymous_established_account"]
                    ),
                },
            }
        )
    count = 6 if salary_anchor else rng.randint(6, 8)
    cash_count = (
        rng.choice([1, 2])
        if family == "cash"
        else rng.choice([0, 1])
        if family in {"mixed", "ambiguous"}
        else 0
    )
    codes = ["cash_withdrawal"] * cash_count + ["card_transfer"] * (count - cash_count)
    rng.shuffle(codes)
    remaining = target
    for i, code in enumerate(codes):
        left = len(codes) - i - 1
        spec = specs[code]
        lo = max(
            int(spec.min_amount),
            remaining - sum(int(specs[c].max_amount) for c in codes[i + 1 :]),
        )
        hi = min(
            int(spec.max_amount),
            remaining - sum(int(specs[c].min_amount) for c in codes[i + 1 :]),
        )
        if lo > hi:
            raise ValueError("Invalid amount partition")
        amount = remaining if not left else rng.randint(lo, hi)
        if family == "repeated" and left and lo <= 50000 <= hi:
            amount = 50000
        raw.append({"code": code, "amount": amount})
        remaining -= amount
    rng.shuffle(raw)
    for s in raw:
        spec = specs[s["code"]]
        if s["code"] == "salary":
            continue
        velocity = rng.choice(
            ["normal", "rapid", "normal", "rapid", "spaced"]
            if variant % 2 == 0
            else ["rapid", "rapid", "normal"]
        )
        s["context"] = {
            "channel": rng.choice(
                list(spec.channels) + [c for c in spec.channels if c != "branch"] * 3
            ),
            "velocity": velocity,
            "time_of_day": rng.choice(["day"] * 5 + ["evening"] * 2 + ["night"]),
        }
        if s["code"] == "card_transfer":
            s["context"]["recipient_type"] = rng.choice(
                ["known_counterparty"] * 5
                + ["new_counterparty"] * 2
                + ["anonymous_wallet"]
            )
    if salary_anchor:
        next(s for s in raw if s["code"] == "salary")["details"]["income_basis"] = [
            "payroll_registry",
            "service_contract",
            "no_reference",
        ][variant // 2]
        for s in raw:
            if s["code"] == "salary":
                continue
            s["context"]["channel"] = (
                "bank" if s["code"] == "incoming_transfer" else "mobile"
            )
            s["context"]["velocity"] = rng.choice(["rapid"] * 5 + ["normal"])
            if s["code"] == "incoming_transfer":
                s["details"] = {
                    "transfer_source": "domestic_bank",
                    "sender_relationship": "regular_sender",
                }
    return normalize(raw, config)


def generate_references(config, rubric, settings):
    rng = random.Random(settings["seed"])
    rows, diagnostics, seen = [], [], set()
    for family in settings["families"]:
        for variant in range(8):
            template = f"{family['id']}_{variant + 1:02d}"
            for _ in range(settings["max_attempts_per_sample"]):
                steps = candidate(rng, family["id"], config, variant)
                record = make_record(steps, config, rubric, family["id"], template)
                if not record["evaluation"]["can_submit"]:
                    if len(diagnostics) < settings["diagnostic_limit"]:
                        diagnostics.append(record)
                    continue
                if record["scenario_id"] not in seen:
                    record["source_refs"] = family["sources"]
                    record["limitations"] = (
                        "Нет истории клиента, точных временных меток и ID контрагентов; семейство не является меткой преступления."
                    )
                    record["observed_signals"] = [
                        c["feature"] for c in record["reasons"] if c["points"]
                    ]
                    rows.append(record)
                    seen.add(record["scenario_id"])
                    break
            else:
                raise ValueError(f"Could not produce valid reference: {template}")
    return rows, diagnostics


def mutate(reference, rng, config):
    steps = deepcopy(reference["steps"])
    specs = snapshot_specs(config)
    for step in steps:
        spec = specs[(step["card"]["code"], step["card"]["version"])]
        step["amount"] = (
            f"{max(spec.min_amount, min(spec.max_amount, float(step['amount']) + rng.randint(-3000, 3000))):.2f}"
        )
        if spec.channels and rng.random() < 0.2:
            step["context"]["channel"] = rng.choice(list(spec.channels))
        for name in ("velocity", "time_of_day", "recipient_type"):
            if name in step["context"] and rng.random() < 0.2:
                field = next(f for f in spec.context_fields if f["key"] == name)
                step["context"][name] = rng.choice(
                    [v["value"] for v in field["options"]]
                )
        for field in spec.fields:
            if rng.random() < 0.2:
                step["action_details"][field["key"]] = rng.choice(
                    [v["value"] for v in field["options"]]
                )
    if rng.random() < 0.2:
        a, b = rng.sample(range(len(steps)), 2)
        steps[a], steps[b] = steps[b], steps[a]
    # Re-normalise IDs after mutations as for any participant input.
    return normalize(
        [
            {
                "code": s["card"]["code"],
                "amount": s["amount"],
                "context": s["context"],
                "details": s["action_details"],
            }
            for s in steps
        ],
        config,
    )


def split_rows(rows, seed):
    """Union template groups sharing content OR a feature vector before splitting."""
    parent = {r["template_id"]: r["template_id"] for r in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owners = {}
    for row in rows:
        for key in (row["scenario_id"], digest(row["features"])):
            group = row["template_id"]
            if key in owners:
                parent[find(group)] = find(owners[key])
            owners[key] = group
    groups = sorted({find(t) for t in parent})
    if len(groups) < 3:
        raise ValueError("Too few independent template groups for three splits")
    random.Random(seed).shuffle(groups)
    n = len(groups)
    ntrain, nval = min(n - 2, round(n * 0.7)), max(1, round(n * 0.15))
    nval = min(nval, n - ntrain - 1)
    assigned = {
        g: "train" if i < ntrain else "validation" if i < ntrain + nval else "test"
        for i, g in enumerate(groups)
    }
    return [
        {
            "scenario_id": r["scenario_id"],
            "group_id": find(r["template_id"]),
            "split": assigned[find(r["template_id"])],
        }
        for r in rows
    ]


def review_selection(rows):
    selected, seen = [], set()

    def add(candidates, count, category):
        for row in candidates:
            if row["scenario_id"] not in seen:
                selected.append(
                    {
                        "scenario_id": row["scenario_id"],
                        "category": category,
                        "proposed_score": row["target_risk_score"],
                        "reviewed_score": "",
                        "comment": "",
                    }
                )
                seen.add(row["scenario_id"])
                count -= 1
                if count == 0:
                    break
        if count:
            raise ValueError("Insufficient distinct records for pilot review")

    ordered = sorted(rows, key=lambda r: (r["target_risk_score"], r["scenario_id"]))
    add([ordered[round(i * (len(rows) - 1) / 59)] for i in range(60)], 60, "risk_range")
    add(
        sorted(
            rows,
            key=lambda r: min(abs(r["target_risk_score"] - v) for v in [25, 50, 75]),
        ),
        30,
        "boundary",
    )
    add(
        sorted(
            rows, key=lambda r: -abs(r["target_risk_score"] - r["baseline_risk_score"])
        ),
        30,
        "baseline_disagreement",
    )
    return selected


def export(output, rows, diagnostics, config, rubric, settings, stage):
    output = Path(output)
    if output.exists():
        raise ValueError(
            f"Output already exists; use a new version directory: {output}"
        )
    output.mkdir(parents=True)
    # Remove constants from X, but retain complete observables for audit/recompute.
    fields = sorted(
        k for k in rows[0]["features"] if len({r["features"][k] for r in rows}) > 1
    )
    splits = split_rows(rows, settings["seed"])
    write_jsonl(output / "scenarios.jsonl", rows)
    write_jsonl(output / "diagnostics.jsonl", diagnostics)
    write_json(output / "round_config.json", config)
    write_json(output / "rubric.json", rubric)
    write_json(output / "generation.json", settings)
    write_csv(
        output / "features.csv",
        [
            {"scenario_id": r["scenario_id"], **{k: r["features"][k] for k in fields}}
            for r in rows
        ],
        ["scenario_id", *fields],
    )
    write_csv(
        output / "labels.csv",
        [
            {
                "scenario_id": r["scenario_id"],
                "target_risk_score": r["target_risk_score"],
            }
            for r in rows
        ],
        ["scenario_id", "target_risk_score"],
    )
    write_csv(output / "splits.csv", splits, ["scenario_id", "group_id", "split"])
    manifest = {
        "stage": stage,
        "release_status": "pending_user_review",
        "seed": settings["seed"],
        "generator_version": settings["version"],
        "feature_version": FEATURE_VERSION,
        "config_hash": digest(config),
        "rubric_hash": digest(rubric),
        "records_hash": digest(rows),
        "features": fields,
        "categorical_features": [k for k in CATEGORICAL_FEATURES if k in fields],
        "excluded_constant_features": sorted(set(rows[0]["features"]) - set(fields)),
        "rows": len(rows),
        "diagnostic_rows": len(diagnostics),
        "source_hashes": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                Path(__file__),
                ROOT / "src/aml_workshop_simulator/services/aml_dataset_features.py",
            ]
        },
    }
    write_json(output / "manifest.json", manifest)
    distribution = Counter(int(r["target_risk_score"] // 25) * 25 for r in rows)
    coverage = {}
    for key in ("family",):
        coverage[key] = dict(Counter(r[key] for r in rows))
    for feature in ("income_basis", "num_steps", "card_incoming_transfer_count"):
        coverage[feature] = dict(Counter(str(r["features"][feature]) for r in rows))
    coverage["by_risk_family_length"] = dict(
        Counter(
            f"{int(r['target_risk_score'] // 25) * 25}|{r['family']}|{r['features']['num_steps']}"
            for r in rows
        )
    )
    for dimension in ("source", "velocity", "recipient", "sender", "channel", "time"):
        coverage[dimension] = {
            k: sum(r["features"][k] for r in rows)
            for k in rows[0]["features"]
            if k.startswith(dimension + "_") and k.endswith("_count")
        }
    # Find observed comparable-turnover evidence, without manufacturing labels.
    comparable = []
    ordered = sorted(rows, key=lambda r: r["features"]["total_outflow"])
    for left, right in zip(ordered, ordered[1:]):
        if (
            right["features"]["total_outflow"] - left["features"]["total_outflow"]
            <= 1000
            and abs(right["target_risk_score"] - left["target_risk_score"]) >= 15
        ):
            comparable.append(
                {
                    "left": left["scenario_id"],
                    "right": right["scenario_id"],
                    "outflow_gap": right["features"]["total_outflow"]
                    - left["features"]["total_outflow"],
                    "risk_gap": abs(
                        right["target_risk_score"] - left["target_risk_score"]
                    ),
                }
            )
    coverage["comparable_turnover_pairs"] = comparable[:24]
    write_json(output / "coverage.json", coverage)
    report = [
        "# Отчёт качества",
        "",
        f"Этап: {stage}; записей: {len(rows)}. Все основные записи допускают отправку.",
        f"Риск: {min(r['target_risk_score'] for r in rows)}–{max(r['target_risk_score'] for r in rows)}.",
        f"Диапазоны по 25 баллов: {dict(sorted(distribution.items()))}.",
        f"Разбиение: {dict(Counter(s['split'] for s in splits))}.",
        f"Диагностика: сохранено {len(diagnostics)} отклонённых вариантов (ограниченная выборка, не полная статистика).",
        "",
        "Покрытие: coverage.json. Автоматические метки пока не подтверждены пользователем.",
    ]
    (output / "quality_report.md").write_text("\n".join(report) + "\n")
    (output / "dataset_card.md").write_text(
        "# Паспорт датасета\n\nСинтетические сценарии учебной игры, не банковские наблюдения. Цель — учебный риск 0–100.\nМетки получены отдельной рубрикой; статус проверки указан в manifest.json.\nВход модели: только столбцы manifest.features из features.csv, без scenario_id.\nИсходные контексты, объяснения и baseline доступны только для аудита.\nРаспределения генератора не оценивают распространённость преступлений.\nРезультаты на этих данных проверяют освоение рубрики, не реальную эффективность AML.\n"
    )
    if stage == "pilot":
        selected = review_selection(rows)
        write_csv(output / "pilot_review.csv", selected, list(selected[0]))
    return manifest
