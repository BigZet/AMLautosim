from collections import Counter
from copy import deepcopy

import pytest

from scripts.aml_chain_control import controls, freeze
from scripts.aml_dataset import aml_population_author as p
from scripts.build_aml_fixed_history_dataset import common_context


def test_control_outcomes_and_engine_contract():
    rows = controls()
    assert Counter(r["aml_label"] for r in rows) == {0: 10, 1: 10, None: 5}
    assert all(r["public_snapshot"]["config"] == common_context()[0] for r in rows)
    features = p.validate_sources(rows, p.protocol())
    assert len(features) == 25
    # Waiting/personal context cannot reveal private source ownership.
    assert features["control-01"] == features["control-16"]
    assert features["control-02"] == features["control-11"]
    assert features["control-07"] == features["control-15"]


def test_private_narrative_does_not_enter_model_features():
    row = controls()[0]
    changed = deepcopy(row)
    changed["title"] = "Completely different wording"
    changed["author_truth"]["economic_event"] = "Unobservable narrative replacement"
    assert p.validate_sources([row], p.protocol()) == p.validate_sources(
        [changed], p.protocol()
    )


def test_freeze_cannot_be_silently_replaced(tmp_path):
    path = tmp_path / "control"
    result = freeze(path)
    assert result["release_ready"] is False
    assert result["independent_domain_review"] is False
    with pytest.raises(ValueError, match="already exists"):
        freeze(path)
