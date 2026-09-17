from copy import deepcopy

from scripts.aml_chain_control import steps_for, controls
from src.aml_workshop_simulator.services.aml_pattern_policy import (
    chain_features,
    label_pattern,
)


def test_identical_observations_have_same_label_despite_opposite_private_truth():
    rows = controls()
    for a, b in ((0, 15), (1, 10), (6, 14)):
        assert rows[a]["aml_label"] != rows[b]["aml_label"]
        assert label_pattern(
            chain_features(rows[a]["public_snapshot"]["steps"])
        ) == label_pattern(chain_features(rows[b]["public_snapshot"]["steps"]))


def test_one_fast_transfer_is_not_a_pattern():
    steps = steps_for("relay", {}, "one")[:2]
    assert label_pattern(chain_features(steps)) == (0, [])


def test_renaming_parties_preserves_chain_pattern():
    steps = steps_for("relay", {}, "original")
    renamed = deepcopy(steps)
    for step in renamed:
        for key in ("sender_id", "recipient_id"):
            if key in step:
                step[key] = "renamed-" + step[key]
    assert chain_features(steps) == chain_features(renamed)


def test_delaying_every_outgoing_breaks_rapid_pattern_not_just_any_wait():
    steps = steps_for("relay", {}, "wait")
    assert label_pattern(chain_features(steps))[0] == 1
    for step in steps:
        if step["card"]["code"] in ("card_transfer", "cash_withdrawal"):
            step["interval_minutes"] = 60
    assert label_pattern(chain_features(steps))[0] == 0


def test_fragmentation_can_be_standalone_and_is_not_silently_covered_by_fanout():
    steps = steps_for("split", {}, "split")
    for step in steps:
        if step["card"]["code"] == "incoming_transfer":
            step["sender_id"] = "A"
        else:
            step["recipient_id"] = "B"
    assert label_pattern(chain_features(steps)) == (1, ["repeated_fragmentation"])
