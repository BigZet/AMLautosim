"""Review forms bind human decisions to exact observable records and rubric."""

import csv
import json
import math
from pathlib import Path

FIELDS = ["id", "observable_hash", "decision", "reviewed_score", "reason"]


def prepare_forms(package, destination, manifest):
    for key, filename in [
        ("references", "reference-decisions.csv"),
        ("challenges", "blind-decisions.csv"),
    ]:
        with (destination / filename).open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(
                dict(
                    id=r["id"],
                    observable_hash=r["observable_hash"],
                    decision="",
                    reviewed_score="",
                    reason="",
                )
                for r in package[key]
            )
    (destination / "review-decision.json").write_text(
        json.dumps(
            dict(
                status="pending",
                package_hash=manifest["package_hash"],
                rubric_hash=manifest["rubric_hash"],
                reviewer="",
                reviewed_at="",
                user_decision_evidence="",
                rubric_accepted=False,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def check_decisions(directory, records, filename, blind=False):
    with (directory / filename).open() as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != FIELDS:
            raise ValueError("Unexpected review columns")
        rows = list(reader)
    expected = {r["id"]: r for r in records}
    if len(rows) != len(expected) or {r["id"] for r in rows} != set(expected):
        raise ValueError("Review must cover every record exactly once")
    for row in rows:
        original = expected[row["id"]]
        if row["observable_hash"] != original["observable_hash"]:
            raise ValueError("Review belongs to a different observable chain")
        choices = ("independent",) if blind else ("accept", "revise")
        if row["decision"] not in choices:
            raise ValueError(f"Human decision missing for {row['id']}")
        try:
            score = float(row["reviewed_score"])
        except ValueError as error:
            raise ValueError(f"Human score missing for {row['id']}") from error
        if not math.isfinite(score) or not 0 <= score <= 100:
            raise ValueError("Human score must be finite and within 0..100")
        if not row["reason"].strip():
            raise ValueError("Human reasoning is required")
        if not blind and (
            row["decision"] != "accept" or score != original["target_risk_score"]
        ):
            raise ValueError(
                "Corrections require a revised rubric/package and another review"
            )
    return rows


def check_joint_review(directory, require_blind=False):
    from scripts.validate_expanded_aml_dataset import validate_directory
    from datetime import datetime

    directory = Path(directory)
    validate_directory(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    decision = json.loads((directory / "review-decision.json").read_text())
    for key in ("package_hash", "rubric_hash"):
        if decision[key] != manifest[key]:
            raise ValueError("Review belongs to another package or rubric")
    if decision["status"] != "approved" or decision["rubric_accepted"] is not True:
        raise ValueError("Joint rubric review is pending")
    if (
        not decision["reviewer"].strip()
        or not decision["user_decision_evidence"].strip()
    ):
        raise ValueError("Reviewer and explicit user decision evidence are required")
    if datetime.fromisoformat(decision["reviewed_at"]).tzinfo is None:
        raise ValueError("Review time requires timezone")
    references = [
        json.loads(line)
        for line in (directory / "references.jsonl").read_text().splitlines()
    ]
    check_decisions(directory, references, "reference-decisions.csv")
    if require_blind:
        blind = [
            json.loads(line)
            for line in (directory / "challenges.jsonl").read_text().splitlines()
        ]
        check_decisions(directory, blind, "blind-decisions.csv", blind=True)
    return {
        "rubric_and_references": "approved",
        "blind_review_checked": require_blind,
        "release_authorized": False,
        "remaining": "pilot 2000 and joint review according to its review-policy.json before release",
    }
