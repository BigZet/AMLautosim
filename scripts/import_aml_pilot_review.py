"""Import explicit CSV judgments as data; revisions never approve a release."""

import argparse
import csv
import hashlib
import io
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from scripts.aml_dataset.expanded import digest
from scripts.aml_dataset.joint_review import FIELDS
from scripts.aml_dataset.mass_release import review_contract, read_json, read_rows


def import_review(pilot, source):
    pilot, source = Path(pilot), Path(source)
    contract = review_contract(pilot)
    sample = read_rows(pilot / contract["sample"])
    expected = {r["record"]["id"]: r["record"] for r in sample}
    raw = source.read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if reader.fieldnames != FIELDS:
        raise ValueError("Unexpected review columns")
    rows = list(reader)
    if len(rows) != len(expected) or {r["id"] for r in rows} != set(expected):
        raise ValueError("Missing, duplicate or unknown review cases")
    diffs = []
    for row in rows:
        if set(row) != set(FIELDS) or any(not isinstance(v, str) for v in row.values()):
            raise ValueError("Malformed review row")
        case = expected[row["id"]]
        if row["observable_hash"] != case["observable_hash"]:
            raise ValueError("Review belongs to a different observable scenario")
        if row["decision"] not in ("accept", "revise") or not row["reason"].strip():
            raise ValueError("Every case requires an explicit decision and reason")
        score = float(row["reviewed_score"])
        if not math.isfinite(score) or not 0 <= score <= 100:
            raise ValueError("Score must be finite and in range 0-100")
        if row["decision"] == "accept" and score != case["target_risk_score"]:
            raise ValueError("Accepted score differs from the proposal")
        diffs.append(dict(id=row["id"], decision=row["decision"],
                          proposed=case["target_risk_score"], reviewed=score,
                          delta=round(score - case["target_risk_score"], 4), reason=row["reason"]))
    # No file mutations occur before the whole submission is checked.
    sha = hashlib.sha256(raw).hexdigest()
    receipt = pilot / "review-submissions" / (sha + ".csv")
    receipt.parent.mkdir(exist_ok=True)
    if not receipt.exists():
        receipt.write_bytes(raw)
    decisions_path = pilot / contract["decisions"]
    old = decisions_path.read_bytes()
    old_receipt = receipt.parent / (hashlib.sha256(old).hexdigest() + ".previous.csv")
    if not old_receipt.exists():
        old_receipt.write_bytes(old)
    with decisions_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    manifest = read_json(pilot / "manifest.json")
    revisions = sum(r["decision"] == "revise" for r in rows)
    report = dict(status="changes_requested" if revisions else "approved",
                  accepted=len(rows) - revisions, revisions=revisions, cases=diffs,
                  source_sha256=sha, imported_at=datetime.now(timezone.utc).isoformat())
    (receipt.parent / (sha + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    decision_path = pilot / contract["decision"]
    previous = decision_path.read_bytes()
    archive = receipt.parent / (hashlib.sha256(previous).hexdigest() + ".previous-decision.json")
    if not archive.exists():
        archive.write_bytes(previous)
    decision = dict(status=report["status"], pilot_rows_hash=manifest["rows_hash"],
                    sample_hash=digest(sample), reviewer="User via exported review CSV",
                    reviewed_at=report["imported_at"], timestamp_basis="receipt import time",
                    user_decision_evidence=str(receipt), source_sha256=sha)
    decision_path.write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--pilot", required=True)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    report = import_review(args.pilot, args.input)
    print({k: v for k, v in report.items() if k != "cases"})
