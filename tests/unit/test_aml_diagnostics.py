import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.aml_dataset.aml_casebook import protocol
from scripts.aml_dataset.aml_training import derive, validate_sources


def reviewed_pair():
    rows = [json.loads(line) for line in Path(
        "resources/aml_dataset/aml-v1/origins-reviewed/v3/casebook.jsonl"
    ).read_text(encoding="utf-8").splitlines()]
    return [row for row in rows if row["provenance"]["root_id"] == "service_jobs"
            and row["variant_recipe"] == "schedule-0-records"]


def test_mask_keeps_economic_truth_and_parent_without_inheriting_approval():
    from scripts.aml_dataset.aml_diagnostics import mask_evidence

    source = reviewed_pair()[0]
    saved = deepcopy(source)
    masked = mask_evidence(source)
    assert source == saved
    assert masked["author_truth"] == source["author_truth"]
    assert masked["aml_label"] == source["aml_label"]
    assert masked["review_status"] == "authored_unreviewed"
    assert masked["review"] is None
    assert masked["provenance_group_id"] == source["provenance_group_id"]
    assert source["scenario_id"] in masked["provenance"]["parent_ids"]
    assert masked["challenge_set"] == "masked-context"
    assert masked["public_snapshot"]["config"]["behavior"]["aml_context"]["facts"] == []


def test_masked_counterfactuals_remain_valid_and_observationally_identical():
    from scripts.aml_dataset.aml_diagnostics import mask_evidence

    parents = reviewed_pair()
    masked = [mask_evidence(row) for row in parents]
    features = validate_sources(masked, protocol())
    assert len(features) == 2
    assert masked[0]["public_snapshot"] == masked[1]["public_snapshot"]
    assert features[masked[0]["scenario_id"]] == features[masked[1]["scenario_id"]]
    artifacts, audit = derive(parents + masked, protocol())
    assert audit["confirmed_rows"] == 2
    assert audit["all_connected_groups"] == 1
    assert audit["diagnostic_rows"] == {"masked-context": 2}
    assert "independent_diagnostic_review" in audit["unmet_gates"]
    diagnostics = [json.loads(line) for line in artifacts[
        "diagnostics/masked-context.jsonl"].decode().splitlines()]
    assert all(row["independent"] is False for row in diagnostics)
    assert all(row["parent_split"] == "train" for row in diagnostics)


@pytest.mark.parametrize("defect", ["unreviewed", "modified", "already_masked"])
def test_mask_refuses_unbound_changed_or_repeated_source(defect):
    from scripts.aml_dataset.aml_diagnostics import mask_evidence

    source = reviewed_pair()[0]
    if defect == "unreviewed":
        source.update(review_status="authored_unreviewed", review=None)
    elif defect == "modified":
        source["aml_label"] = 1 - source["aml_label"]
    else:
        source = mask_evidence(source)
    with pytest.raises(ValueError):
        mask_evidence(source)
