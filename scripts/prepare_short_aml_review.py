"""Apply the user's documented 12-case, non-blind pilot review policy."""

import argparse
import csv
import json
from pathlib import Path

from scripts.aml_dataset.expanded import digest, stable
from scripts.aml_dataset.joint_review import FIELDS
from scripts.aml_dataset.mass_release import read_rows, review_sample, validate_mass


def prepare(directory):
    directory = Path(directory)
    validate_mass(directory)
    names = ("review-policy.json", "review12.jsonl", "pilot-decisions-short.csv",
             "pilot-decision-short.json")
    if any((directory / name).exists() for name in names):
        raise FileExistsError("Short review already exists; do not overwrite judgments")
    rows = read_rows(directory / "scenarios.jsonl")
    sample = review_sample(rows, (4, 4, 4))
    manifest = json.loads((directory / "manifest.json").read_text())
    (directory / "review12.jsonl").write_text("".join(stable(r) + "\n" for r in sample))
    with (directory / "pilot-decisions-short.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({"id": r["record"]["id"], "observable_hash": r["record"]["observable_hash"]} for r in sample)
    decision = dict(status="pending", pilot_rows_hash=manifest["rows_hash"],
                    sample_hash=digest(sample), reviewer="", reviewed_at="",
                    user_decision_evidence="")
    (directory / "pilot-decision-short.json").write_text(json.dumps(decision, indent=2) + "\n")
    (directory / "review-policy.json").write_text(json.dumps(dict(
        version="human-12-no-blind-v1",
        user_evidence="User accepted reducing review, requested all cases at once and no blind assessment. See docs/verification/aml-pilot-stage07.md.",
        independent_blind_review_required=False,
    ), indent=2) + "\n")
    return {"count": len(sample), "blind_required": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("directory")
    print(prepare(parser.parse_args().directory))
