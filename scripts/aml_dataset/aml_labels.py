"""Strict authored AML labels; never derived from behavioral risk scores."""
from datetime import date

FORBIDDEN_PUBLIC = {"review", "reviewer", "method", "rationale", "author_id", "label_protocol_version", "population_id", "hypothesis_source", "alternative_explanation", "necessary_facts", "forbidden_information", "observability", "economic_records", "expected_evidence", "aml_label", "label_status", "review_status", "label_source", "label_rationale", "author_truth", "investigation", "investigation_outcome", "risk_score", "split", "family_id", "scenario_id", "provenance_group_id"}

def validate_label(record: dict) -> None:
    if not isinstance(record, dict):
        raise ValueError("label record requires an object")
    status, label = record.get("label_status"), record.get("aml_label")
    if status == "unresolved":
        if label is not None:
            raise ValueError("unresolved requires aml_label=null")
    elif status == "confirmed":
        if type(label) is not int or label not in (0, 1):
            raise ValueError("confirmed requires integer aml_label 0 or 1")
    else:
        raise ValueError("invalid label_status")
    review = record.get("review_status")
    if not isinstance(review, str) or review not in {"authored_unreviewed", "reviewed", "rejected"}:
        raise ValueError("invalid review_status")
    for key in ("scenario_id", "provenance_group_id", "family_id", "label_source", "label_protocol_version", "label_rationale", "population_id", "author_id"):
        if not isinstance(record.get(key), str) or not record[key].strip():
            raise ValueError(f"missing {key}")
    if record["label_protocol_version"] != "aml-labels-v1":
        raise ValueError("unsupported label_protocol_version")
    for field in ("author_truth", "observability", "hypothesis_source", "alternative_explanation", "public_snapshot"):
        if not isinstance(record.get(field), dict):
            raise ValueError(f"{field} requires an object")
    truth = record["author_truth"]
    if truth.get("aml_episode_present") is not None and type(truth.get("aml_episode_present")) is not bool:
        raise ValueError("author_truth outcome requires boolean or null")
    if type(record["observability"].get("distinguishable")) is not bool or not isinstance(record["observability"].get("reason"), str) or not record["observability"]["reason"].strip():
        raise ValueError("observability requires boolean and nonblank reason")
    for field in ("necessary_facts", "forbidden_information"):
        values = record.get(field)
        if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError(f"{field} requires nonblank string list")
    public = record["public_snapshot"]
    if not isinstance(public.get("config"), dict) or not isinstance(public.get("steps"), list):
        raise ValueError("public_snapshot requires config object and steps list")
    if record.get("review") is not None and not isinstance(record["review"], dict):
        raise ValueError("review requires an object or null")
    if review == "reviewed":
        evidence = record.get("review") or {}
        if any(not isinstance(evidence.get(k), str) or not evidence[k].strip() for k in ("reviewer", "method", "date", "rationale")) or evidence["reviewer"] == record["author_id"]:
            raise ValueError("review requires independent reviewer/method/date/rationale")
        try:
            date.fromisoformat(evidence["date"])
        except (ValueError, TypeError):
            raise ValueError("review date requires ISO calendar date") from None
        if evidence["method"] not in {"independent_domain_review", "human_domain_review"}:
            raise ValueError("review method cannot be automated validation")

def validate_public(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_PUBLIC:
                raise ValueError(f"forbidden public key: {key}")
            validate_public(child)
    elif isinstance(value, list):
        for child in value:
            validate_public(child)
