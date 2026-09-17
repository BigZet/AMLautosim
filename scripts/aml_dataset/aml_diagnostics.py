"""Evidence-removal diagnostics retain their original economic provenance.

These are new unreviewed observations, never extra independent training cases.
The original reviewed source and its approval are left untouched.
"""

from copy import deepcopy

from scripts.aml_dataset.aml_labels import validate_label, validate_public
from scripts.aml_dataset.aml_review import record_hash, verify_review_binding

VERSION = "aml-mask-evidence-v1"


def mask_evidence(source: dict) -> dict:
    """Remove available evidence without changing transactions or hidden outcome."""
    validate_label(source)
    if source.get("challenge_set") or not verify_review_binding(source):
        raise ValueError("Mask requires an unmodified independently reviewed main case")
    if source["label_status"] != "confirmed":
        raise ValueError("Masked-context diagnostic requires a known authored outcome")
    row = deepcopy(source)
    context = row["public_snapshot"]["config"]["behavior"]["aml_context"]
    if not context["facts"]:
        raise ValueError("No observable evidence to mask")
    removed = [fact["id"] for fact in context["facts"]]
    context["facts"] = []
    context["opening_balance_facts"] = []
    for step in row["public_snapshot"]["steps"]:
        if step.get("claim_id") is not None:
            step["claim_id"] = None
    row.update(
        scenario_id=source["scenario_id"] + "--masked-evidence-v1",
        challenge_set="masked-context",
        review_status="authored_unreviewed",
        review=None,
        author_id=VERSION,
        variant_recipe=source.get("variant_recipe", "") + "/" + VERSION,
    )
    provenance = row.setdefault("provenance", {})
    provenance["parent_ids"] = sorted(set(
        provenance.get("parent_ids", []) + [source["scenario_id"]]
    ))
    row["masking"] = {
        "version": VERSION,
        "source_scenario_id": source["scenario_id"],
        "source_record_sha256": record_hash(source),
        "removed_fact_ids": removed,
        "independent": False,
        "scope": "Evidence removed; history, declared purposes and economic truth retained",
    }
    row["observability"] = {
        "distinguishable": False,
        "reason": "Evidence removed; distinguishability is not established by the parent review. Requires diagnostic-specific review; no target probability is prescribed.",
    }
    validate_label(row)
    validate_public(row["public_snapshot"])
    return row
