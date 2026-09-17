from copy import deepcopy

from scripts.aml_game_curriculum import candidate, catalog
from scripts.build_aml_game_dataset import family_counts
from scripts.aml_dataset.aml_training import evaluate, submit_blockers
from src.aml_workshop_simulator.services.aml_game_pattern_panel_v2 import (
    assess_panel,
    extract_panel_features,
)


def assessment(steps):
    return assess_panel(extract_panel_features(steps))


def valid_family(family):
    for i in range(100):
        config, steps, _, _ = candidate(24 * i + family)
        if not submit_blockers(evaluate(steps, config)):
            yield config, steps


def test_fixed_context_and_multiple_low_risk_resource_strategies():
    original = deepcopy(catalog()[0])
    low_families = set()
    for family in range(15, 21):
        for config, steps in valid_family(family):
            assert config == original
            if assessment(steps)["target_probability"] < 0.1:
                low_families.add(family)
                break
    assert len(low_families) >= 4
    assert catalog()[0] == original


def test_party_renaming_does_not_change_features_or_target():
    _, steps = next(valid_family(17))
    renamed = deepcopy(steps)
    for step in renamed:
        for field in ("sender_id", "recipient_id"):
            if field in step:
                step[field] = "renamed-" + step[field]
    assert extract_panel_features(steps) == extract_panel_features(renamed)
    assert assessment(steps) == assessment(renamed)


def test_structural_fragmentation_survives_valid_waits():
    config, steps = next(valid_family(23))
    assert not submit_blockers(evaluate(steps, config))
    assert assessment(steps)["rule_support"]["fragmentation"] == 603
    assert assessment(steps)["target_probability"] >= 0.9


def test_small_conserved_amount_changes_do_not_create_score_cliffs():
    for family in range(24):
        _, steps = next(valid_family(family))
        changed = deepcopy(steps)
        cards = [s for s in changed if s["card"]["code"] == "card_transfer"]
        cards[0]["amount"] = str(float(cards[0]["amount"]) + 0.01)
        cards[1]["amount"] = str(float(cards[1]["amount"]) - 0.01)
        assert abs(assessment(steps)["target_probability"] -
                   assessment(changed)["target_probability"]) <= 0.01


def test_curriculum_counts_cover_every_family_and_requested_size():
    counts = family_counts(30000)
    assert set(counts) == set(range(24))
    assert sum(counts.values()) == 30000
    assert sum(counts[i] for i in range(15, 21)) == 18000
