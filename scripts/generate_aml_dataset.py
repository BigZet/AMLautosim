"""Usage: python -m scripts.generate_aml_dataset --stage review --output PATH."""

import argparse
import hashlib
import math
import random
from copy import deepcopy
from pathlib import Path

from scripts.aml_dataset.core import (
    CONFIG,
    candidate,
    content_hash,
    digest,
    export,
    frozen_config,
    generate_references,
    make_record,
    mutate,
    read_json,
    read_jsonl,
    write_csv,
    write_json,
    write_jsonl,
)


def require_approval(path, expected):
    if path is None:
        raise ValueError(
            "Joint review is required before mass labeling; supply its approval JSON"
        )
    approval = read_json(path)
    if approval.get("status") != "approved" or not approval.get("reviewer"):
        raise ValueError("Approval must identify a reviewer and approved status")
    for key, value in expected.items():
        if approval.get(key) != value:
            raise ValueError(f"Approval does not match reviewed artifact: {key}")
    return approval


def review_materials(output, rows, config, rubric, settings):
    output = Path(output)
    from src.aml_workshop_simulator.services.configuration import snapshot_specs

    specs = snapshot_specs(config)

    def describe(step, detail=False):
        spec = specs[(step["card"]["code"], step["card"]["version"])]
        fields = spec.fields if detail else spec.context_fields
        values = step["action_details"] if detail else step["context"]
        result = []
        for field in fields:
            value = values.get(field["key"], "")
            display = next(
                (o["label"] for o in field["options"] if o["value"] == value), value
            )
            result.append(f"{field['label']}: {display}")
        if not detail and "channel" in values:
            result.append("Канал: " + str(values["channel"]))
        return "; ".join(result) or "—"

    lines = [
        "# Эталоны для совместной проверки",
        "",
        "Предварительные оценки автора. Веса не согласованы.\n",
        "Баллы не являются вероятностью преступления или срабатывания банка.",
        "",
        "## Веса рубрики",
        "",
    ]
    for term in rubric["terms"]:
        lines.append(f"- {term['weight']}: {term['reason']}.")
    lines += [
        "",
        *rubric["exceptions"],
        "",
        "## Сводка",
        "",
        "| Эталон | Балл | Оборот списаний | Время / энергия после |",
        "|---|---:|---:|---|",
    ]
    for row in rows:
        e = row["evaluation"]
        lines.append(
            f"| {row['template_id']} | {row['target_risk_score']} | {e['totals']['gross_outflow']} | {e['resources_after']['time']} / {e['resources_after']['energy']} |"
        )
    for row in rows:
        lines += [
            "",
            f"## {row['template_id']} — {row['target_risk_score']} балла",
            "",
            "Источники: "
            + ", ".join(f"[{s}]({settings['sources'][s]})" for s in row["source_refs"]),
            "",
            row["limitations"],
            "",
            "| Шаг | Карточка | Сумма | Контекст | Детали |",
            "|---|---|---:|---|---|",
        ]
        for i, step in enumerate(row["steps"], 1):
            lines.append(
                f"| {i} | {specs[(step['card']['code'], step['card']['version'])].title} | {step['amount']} | {describe(step)} | {describe(step, True)} |"
            )
        lines += [
            "",
            "Вклады: "
            + "; ".join(
                f"{c['reason']}: {c['points']:.2f}"
                for c in row["reasons"]
                if c["points"]
            )
            + ".",
            "",
            "Решение пользователя: пока не получено.",
        ]
    (output / "reference_review.md").write_text("\n".join(lines) + "\n")
    approval = {
        "status": "pending",
        "reviewer": None,
        "rubric_hash": digest(rubric),
        "reference_hash": digest(rows),
        "config_hash": digest(config),
        "notes": "Заполняется только по результату совместной проверки, не автоматически.",
    }
    write_json(output / "approval.json", approval)
    # Blind challenge: separate seed, new ordering patterns, no rubric scores shown.
    rng = random.Random(settings["seed"] + 1)
    challenge, seen = [], {r["scenario_id"] for r in rows}
    for i in range(settings["challenge_samples"]):
        family = settings["families"][i % 6]["id"]
        for _ in range(settings["max_attempts_per_sample"]):
            steps = candidate(rng, family, config, i + 8)
            r = make_record(steps, config, rubric, family, f"challenge_{i + 1:02d}")
            if r["evaluation"]["can_submit"] and r["scenario_id"] not in seen:
                challenge.append(
                    {
                        k: r[k]
                        for k in [
                            "scenario_id",
                            "template_id",
                            "family",
                            "steps",
                            "config_hash",
                            "evaluation",
                        ]
                    }
                )
                seen.add(r["scenario_id"])
                break
        else:
            raise ValueError("Could not construct independent challenge")
    write_jsonl(output / "challenge_blind.jsonl", challenge)
    write_csv(
        output / "challenge_review.csv",
        [
            {
                "scenario_id": r["scenario_id"],
                "reviewed_score": "",
                "reason": "",
                "reviewer": "",
            }
            for r in challenge
        ],
        ["scenario_id", "reviewed_score", "reason", "reviewer"],
    )
    # Counterfactual checks remain diagnostic if a mutation violates game limits.
    pairs = []
    for kind in ["source", "tempo", "order", "salary"]:
        for row in rows[:6]:
            steps = deepcopy(row["steps"])
            if kind == "source":
                step = next(
                    s for s in steps if s["card"]["code"] == "incoming_transfer"
                )
                step["action_details"]["transfer_source"] = (
                    "domestic_bank"
                    if step["action_details"]["transfer_source"] != "domestic_bank"
                    else "foreign_bank_kg"
                )
                expected = "equal"
            elif kind == "tempo":
                step = next(
                    s
                    for s in steps
                    if s["card"]["code"] in {"card_transfer", "cash_withdrawal"}
                )
                step["context"]["velocity"] = "rapid"
                expected = "not_lower"
            elif kind == "order":
                steps[0], steps[-1] = steps[-1], steps[0]
                expected = "recompute_sequence"
            else:
                # Remove existing salary or append one. Neutral at the tail;
                # earlier salary can interrupt a transition, a real observable change.
                from scripts.aml_dataset.core import normalize

                if any(s["card"]["code"] == "salary" for s in steps):
                    steps = [s for s in steps if s["card"]["code"] != "salary"]
                    expected = "recompute_sequence"
                else:
                    salary = normalize([{"code": "salary", "amount": 25000}], config)[0]
                    steps.append(salary)
                    expected = "equal"
            changed = make_record(
                steps, config, rubric, row["family"], row["template_id"]
            )
            before, after = row["target_risk_score"], changed["target_risk_score"]
            passed = (
                after == before
                if expected == "equal"
                else after >= before
                if expected == "not_lower"
                else True
            )
            if not passed:
                raise ValueError(f"Counterfactual failed: {kind}")
            pairs.append(
                {
                    "kind": kind,
                    "parent_id": row["scenario_id"],
                    "expected": expected,
                    "before": before,
                    "after": after,
                    "checked": passed,
                    "variant": changed,
                }
            )
    write_jsonl(output / "counterfactual_pairs.jsonl", pairs)


def run(
    stage,
    output,
    reference_dir=None,
    approval=None,
    pilot_dir=None,
    pilot_approval=None,
):
    settings = read_json(CONFIG / "generation.json")
    rubric = read_json(CONFIG / "rubric.json")
    config = frozen_config()
    if Path(output).exists():
        raise ValueError("Output exists; choose a new directory")
    if stage == "review":
        rows, diagnostics = generate_references(config, rubric, settings)
        manifest = export(output, rows, diagnostics, config, rubric, settings, stage)
        review_materials(output, rows, config, rubric, settings)
    else:
        if reference_dir is None:
            raise ValueError("--reference-dir is required")
        reference_dir = Path(reference_dir)
        from scripts.validate_aml_dataset import read_csv, validate

        validate(reference_dir)
        references = read_jsonl(reference_dir / "scenarios.jsonl")
        expected = {
            "rubric_hash": digest(rubric),
            "reference_hash": digest(references),
            "config_hash": digest(config),
        }
        signed = require_approval(approval, expected)
        if stage == "release":
            if pilot_dir is None:
                raise ValueError("--pilot-dir is required")
            validate(pilot_dir)
            pilot_manifest = read_json(Path(pilot_dir) / "manifest.json")
            if (
                pilot_manifest["stage"] != "pilot"
                or pilot_manifest["rubric_hash"] != digest(rubric)
                or pilot_manifest["config_hash"] != digest(config)
            ):
                raise ValueError("Pilot configuration/rubric mismatch")
            require_approval(
                pilot_approval, {"pilot_manifest_hash": digest(pilot_manifest)}
            )
            for path, expected_count, comment_key in [
                (Path(pilot_dir) / "pilot_review.csv", 120, "comment"),
                (reference_dir / "challenge_review.csv", 24, "reason"),
            ]:
                reviewed = read_csv(path)
                if (
                    len(reviewed) != expected_count
                    or len({r["scenario_id"] for r in reviewed}) != expected_count
                ):
                    raise ValueError(f"Incomplete review: {path}")
                expected_ids = (
                    {
                        r["scenario_id"]
                        for r in read_jsonl(reference_dir / "challenge_blind.jsonl")
                    }
                    if expected_count == 24
                    else {
                        r["scenario_id"]
                        for r in read_jsonl(Path(pilot_dir) / "scenarios.jsonl")
                    }
                )
                for r in reviewed:
                    value = float(r["reviewed_score"])
                    if (
                        r["scenario_id"] not in expected_ids
                        or not math.isfinite(value)
                        or not 0 <= value <= 100
                        or not r[comment_key].strip()
                    ):
                        raise ValueError(
                            f"Invalid reviewed score or missing explanation: {path}"
                        )
            # Review disagreements must be resolved before signing pilot approval;
            # challenge judgments stay independent of the automatic training rubric.
        rng = random.Random(settings["seed"] + 2)
        n = (
            settings["pilot_samples"]
            if stage == "pilot"
            else settings["release_samples"]
        )
        rows, diagnostics = [], []
        challenge = read_jsonl(reference_dir / "challenge_blind.jsonl")
        seen = {r["scenario_id"] for r in challenge} | {
            r["scenario_id"] for r in references
        }
        for _ in range(n * settings["max_attempts_per_sample"]):
            ref = references[len(rows) % len(references)]
            steps = mutate(ref, rng, config)
            if content_hash(steps) in seen:
                continue
            record = make_record(
                steps, config, rubric, ref["family"], ref["template_id"]
            )
            if not record["evaluation"]["can_submit"]:
                if len(diagnostics) < settings["diagnostic_limit"]:
                    diagnostics.append(record)
                continue
            record["source_refs"] = ref["source_refs"]
            record["limitations"] = ref["limitations"]
            record["observed_signals"] = [
                c["feature"] for c in record["reasons"] if c["points"]
            ]
            rows.append(record)
            seen.add(record["scenario_id"])
            if len(rows) == n:
                break
        if len(rows) < 120:
            raise ValueError("Not enough feasible unique scenarios")
        manifest = export(output, rows, diagnostics, config, rubric, settings, stage)
        write_json(Path(output) / "rubric_approval.json", signed)
        manifest["requested_rows"] = n
        manifest["shortfall"] = n - len(rows)
        write_json(Path(output) / "manifest.json", manifest)
        if stage == "pilot":
            write_json(
                Path(output) / "pilot_approval.json",
                {
                    "status": "pending",
                    "reviewer": None,
                    "pilot_manifest_hash": digest(manifest),
                },
            )
    # Hash the completed export; validator detects accidental or partial edits.
    manifest = read_json(Path(output) / "manifest.json")
    manifest["artifact_hashes"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(Path(output).iterdir())
        if p.name
        not in {
            "manifest.json",
            "approval.json",
            "pilot_approval.json",
            "challenge_review.csv",
            "pilot_review.csv",
        }
    }
    write_json(Path(output) / "manifest.json", manifest)
    if stage == "pilot":
        write_json(
            Path(output) / "pilot_approval.json",
            {
                "status": "pending",
                "reviewer": None,
                "pilot_manifest_hash": digest(manifest),
            },
        )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", choices=["review", "pilot", "release"], default="review"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-dir", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--pilot-dir", type=Path)
    parser.add_argument("--pilot-approval", type=Path)
    args = parser.parse_args()
    try:
        manifest = run(
            args.stage,
            args.output,
            args.reference_dir,
            args.approval,
            args.pilot_dir,
            args.pilot_approval,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(f"Created {manifest['rows']} {args.stage} scenarios at {args.output}")


if __name__ == "__main__":
    main()
