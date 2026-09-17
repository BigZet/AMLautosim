"""Import independent decisions bound to exact authored records.

This is integrity validation of a review, never an automated domain approval.
The untouched authored artifact and the decision artifact remain the evidence.
"""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from scripts.aml_dataset.aml_labels import validate_label


def record_hash(record: dict) -> str:
    return hashlib.sha256(
        json.dumps(record, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def verify_review_binding(record: dict) -> bool:
    """Return false for unbound legacy metadata; reject stale bound approvals."""
    review = record.get("review") or {}
    if record.get("review_status") != "reviewed" or not review.get(
        "reviewed_record_sha256"
    ):
        return False
    source = deepcopy(record)
    source.update(review_status="authored_unreviewed", review=None)
    if record_hash(source) != review["reviewed_record_sha256"]:
        raise ValueError("Independent review record hash mismatch")
    source_hash = review.get("source_casebook_sha256")
    if (
        not isinstance(source_hash, str)
        or len(source_hash) != 64
        or any(c not in "0123456789abcdef" for c in source_hash)
    ):
        raise ValueError("Independent review source hash missing or invalid")
    return True


def apply_review(casebook: Path, review: dict) -> list[dict]:
    raw = Path(casebook).read_bytes()
    if (
        not isinstance(review, dict)
        or review.get("casebook_sha256") != hashlib.sha256(raw).hexdigest()
    ):
        raise ValueError("Review casebook hash mismatch")
    decisions = review.get("cases")
    if not isinstance(decisions, list):
        raise ValueError("Review requires per-case decisions")
    by_id = {}
    for decision in decisions:
        if not isinstance(decision, dict) or not isinstance(
            decision.get("scenario_id"), str
        ):
            raise ValueError("Review decision requires scenario_id")
        identity = decision["scenario_id"]
        if identity in by_id:
            raise ValueError("Duplicate review decision")
        by_id[identity] = decision
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    if len(rows) != len(by_id) or {r["scenario_id"] for r in rows} != set(by_id):
        raise ValueError("Review coverage does not match casebook")
    result = []
    for source in rows:
        validate_label(source)
        decision = by_id[source["scenario_id"]]
        if decision.get("record_sha256") != record_hash(source):
            raise ValueError("Reviewed record hash mismatch")
        if (
            decision.get("decision") != "approved"
            or decision.get("required_fixes") != []
        ):
            raise ValueError("Case lacks unconditional independent approval")
        for field in ("reviewer", "method", "date"):
            if field in decision and decision[field] != review.get(field):
                raise ValueError("Inconsistent reviewer identity or date")
        row = deepcopy(source)
        row["review_status"] = "reviewed"
        row["review"] = {
            "reviewer": review.get("reviewer"),
            "method": review.get("method"),
            "date": review.get("date"),
            "rationale": decision.get("rationale"),
            "reviewer_kind": review.get("reviewer_kind"),
            "reviewed_record_sha256": decision["record_sha256"],
            "source_casebook_sha256": review["casebook_sha256"],
        }
        validate_label(row)
        result.append(row)
    return result
