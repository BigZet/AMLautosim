import csv
import json

import pytest

from scripts.import_aml_pilot_review import import_review
from scripts.aml_dataset.joint_review import FIELDS


def fixture(tmp_path, decision="revise", score="60", observable_hash="hash"):
    pilot = tmp_path / "pilot"
    pilot.mkdir()
    (pilot / "review-policy.json").write_text(json.dumps(dict(
        version="human-12-no-blind-v1", user_evidence="explicit user request")))
    (pilot / "review12.jsonl").write_text(json.dumps(dict(record=dict(
        id="D1", observable_hash="hash", target_risk_score=50))) + "\n")
    (pilot / "manifest.json").write_text('{"rows_hash":"pilot-hash"}')
    (pilot / "pilot-decision-short.json").write_text('{"status":"pending"}')
    (pilot / "pilot-decisions-short.csv").write_text(",".join(FIELDS) + "\n")
    source = tmp_path / "answers.csv"
    with source.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow(dict(id="D1", observable_hash=observable_hash,
                             decision=decision, reviewed_score=score, reason="User feedback"))
    return pilot, source


def test_revisions_are_preserved_and_block_approval(tmp_path):
    pilot, source = fixture(tmp_path)
    report = import_review(pilot, source)
    assert report["status"] == "changes_requested" and report["revisions"] == 1
    assert report["cases"][0]["delta"] == 10
    assert json.loads((pilot / "pilot-decision-short.json").read_text())["status"] == "changes_requested"
    assert (pilot / "review-submissions" / (report["source_sha256"] + ".csv")).read_bytes() == source.read_bytes()


@pytest.mark.parametrize("score,hash,decision", [("NaN", "hash", "revise"),
    ("101", "hash", "revise"), ("50", "stale", "accept"), ("60", "hash", "accept")])
def test_invalid_submission_does_not_mutate_decisions(tmp_path, score, hash, decision):
    pilot, source = fixture(tmp_path, decision, score, hash)
    before = (pilot / "pilot-decisions-short.csv").read_bytes()
    with pytest.raises(ValueError):
        import_review(pilot, source)
    assert (pilot / "pilot-decisions-short.csv").read_bytes() == before
    assert not (pilot / "review-submissions").exists()
