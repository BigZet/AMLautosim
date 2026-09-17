import json
from decimal import Decimal
import pytest

from scripts.build_aml_fixed_history_dataset import (
    BEHAVIOR,
    common_context,
    generate_unit,
)
from scripts.aml_dataset.aml_provenance import digest
from scripts.build_aml_fixed_history_dataset import build
from scripts.audit_aml_fixed_history_dataset import audit
from scripts.audit_aml_history_population import file_hash


def test_all_classes_share_exact_existing_history_and_profile():
    config, _ = common_context()
    baseline = json.loads(BEHAVIOR.read_bytes())
    assert config["behavior"]["history"] == baseline["history"]
    assert config["behavior"]["profile"] == baseline["profile"]
    expected = digest(config)
    for index in (0, 1, 12, 13):
        rows, features, _ = generate_unit((index, 2))
        assert len(rows) == len(features) == 2
        for row in rows:
            assert digest(row["public_snapshot"]["config"]) == expected
            assert row["review_status"] == "authored_unreviewed"
            assert row["aml_label"] == index % 2
            routed = Decimal(row["author_truth"]["criminal_principal_routed"])
            assert (routed > 0) == bool(index % 2)


def test_generation_is_repeatable_and_does_not_mutate_baseline():
    original = BEHAVIOR.read_bytes()
    first = generate_unit((4, 2))
    second = generate_unit((4, 2))
    assert first == second
    assert BEHAVIOR.read_bytes() == original


def test_readback_checks_exact_history_even_if_file_checksum_is_updated(tmp_path):
    output = tmp_path / "data"
    build(output, units=4, variants=2, workers=1)
    result = audit(output)
    assert result["rows"] == 8 and result["identical_full_context"]
    assert result["no_group_or_feature_leakage"]
    assert result["release_ready"] is False
    rows = [
        json.loads(line)
        for line in (output / "casebook.jsonl").read_bytes().splitlines()
    ]
    rows[0]["public_snapshot"]["config"]["behavior"]["history"]["operations"][0][
        "amount"
    ] = "1.00"
    (output / "casebook.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    receipt = json.loads((output / "audit.json").read_bytes())
    receipt["artifact_hashes"]["casebook.jsonl"] = file_hash(output / "casebook.jsonl")
    (output / "audit.json").write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="History/profile/context changed"):
        audit(output)
