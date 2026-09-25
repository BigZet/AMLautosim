from tests.research_support import pilot_path
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest


def review_fixture(tmp_path):
    rows = [json.loads(line) for line in
            pilot_path()
            .read_text(encoding="utf-8").splitlines()]
    # Retain review/hash tests on a case supported by the released purpose contract.
    row = next(row for row in rows if row['scenario_id'] == 'P01-4-0')
    source = tmp_path / "authored.jsonl"
    source.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    review = {
        "reviewer": "test-independent-reviewer",
        "method": "independent_domain_review",
        "date": "2026-09-17",
        "reviewer_kind": "test fixture, not a real review",
        "casebook_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "cases": [
            {
                "scenario_id": row["scenario_id"],
                "decision": "approved",
                "required_fixes": [],
                "rationale": "Test independent decision.",
                "record_sha256": hashlib.sha256(
                    json.dumps(row, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest(),
            }
        ],
    }
    return source, review


def test_only_exact_reviewed_record_can_be_stamped(tmp_path):
    from scripts.aml_dataset.aml_review import apply_review

    source, review = review_fixture(tmp_path)
    records = apply_review(source, review)
    assert records[0]["review_status"] == "reviewed"
    assert records[0]["review"]["reviewer"] == review["reviewer"]
    assert (
        json.loads(source.read_text(encoding="utf-8"))["review_status"]
        == "authored_unreviewed"
    )
    changed = deepcopy(review)
    changed["cases"][0]["record_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash"):
        apply_review(source, changed)


@pytest.mark.parametrize(
    "defect",
    ["missing", "duplicate", "rejected", "pending_fix", "source_hash", "self_review"],
)
def test_invalid_review_cannot_be_imported(tmp_path, defect):
    from scripts.aml_dataset.aml_review import apply_review

    source, review = review_fixture(tmp_path)
    if defect == "missing":
        review["cases"] = []
    elif defect == "duplicate":
        review["cases"] *= 2
    elif defect == "rejected":
        review["cases"][0]["decision"] = "rejected"
    elif defect == "pending_fix":
        review["cases"][0]["required_fixes"] = ["unresolved problem"]
    elif defect == "source_hash":
        review["casebook_sha256"] = "0" * 64
    elif defect == "self_review":
        review["reviewer"] = "codex-casebook-author"
    with pytest.raises(ValueError):
        apply_review(source, review)


def test_export_rejects_changes_after_independent_approval(tmp_path):
    from scripts.aml_dataset.aml_review import apply_review
    from scripts.aml_dataset.aml_training import validate_sources

    source, review = review_fixture(tmp_path)
    rows = apply_review(source, review)
    protocol = json.loads(
        Path("config/ml/aml-classifier-v1-protocol.json").read_text(encoding="utf-8")
    )
    validate_sources(rows, protocol)
    rows[0]["author_truth"]["narrative"] = "Changed after review"
    with pytest.raises(ValueError, match="review.*hash"):
        validate_sources(rows, protocol)


def test_missing_review_binding_cannot_pass_release_gate(tmp_path):
    from scripts.aml_dataset.aml_review import apply_review
    from scripts.aml_dataset.aml_training import derive

    source, review = review_fixture(tmp_path)
    rows = apply_review(source, review)
    rows[0]["review"].pop("reviewed_record_sha256")
    protocol = json.loads(
        Path("config/ml/aml-classifier-v1-protocol.json").read_text(encoding="utf-8")
    )
    _, report = derive(rows, protocol)
    assert "independent_review_binding" in report["unmet_gates"]
