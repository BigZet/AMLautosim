import json

import pytest

from scripts.build_aml_chain_dataset import generate_unit, build, hydrate
from scripts.build_aml_fixed_history_dataset import common_context
from scripts.audit_aml_chain_dataset import audit, nuisance


@pytest.mark.parametrize("index", range(6))
def test_matched_chains_pass_engine_and_keep_parties_amounts_equal(index):
    rows, features, _ = generate_unit((index + 30, 2))
    assert len(rows) == len(features) == 4
    context = common_context()[0]
    for a, b in zip(rows[::2], rows[1::2]):
        assert (a["aml_label"], b["aml_label"]) == (0, 1)
        assert (
            a["public_snapshot"]["config"] == b["public_snapshot"]["config"] == context
        )
        assert nuisance(a["public_snapshot"]["steps"]) == nuisance(
            b["public_snapshot"]["steps"]
        )
        assert a["author_truth"]["aml_episode_present"] is False
        assert b["author_truth"]["aml_episode_present"] is True


def test_compact_readback_rejects_wrong_context(tmp_path):
    root = tmp_path / "corpus"
    build(root, units=12, variants=1, workers=1)
    result = audit(root)
    assert result["rows"] == 24 and result["equal_pair_nuisances"]
    assert not result["release_ready"]
    row = json.loads(
        (root / "casebook.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    context = common_context()[0]
    context["behavior"]["history"]["operations"][0]["amount"] = "1.00"
    with pytest.raises(ValueError, match="Context binding mismatch"):
        hydrate(row, context)
