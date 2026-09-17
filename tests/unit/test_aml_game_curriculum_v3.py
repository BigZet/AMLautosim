from scripts.aml_game_curriculum import candidate as original
from scripts.aml_game_curriculum_v3 import candidate
from scripts.aml_dataset.aml_training import evaluate, submit_blockers
from src.aml_workshop_simulator.services.aml_game_pattern_panel_v2 import extract_panel_features, assess_panel


def test_coverage_repair_changes_only_waits():
    for seed in range(120):
        config, steps, family, topology = candidate(seed)
        old_config, old_steps, old_family, old_topology = original(seed)
        assert (config, family, topology) == (old_config, old_family, old_topology)
        def strip(rows):
            return [{k: v for k, v in s.items() if k != 'interval_minutes'} for s in rows]
        assert strip(steps) == strip(old_steps)
        if family >= 15:
            assert steps == old_steps


def test_incoming_first_can_be_low_without_resource_rule_changes():
    low = 0
    for seed in range(0, 2400, 24):
        config, steps, _, _ = candidate(seed)
        if submit_blockers(evaluate(steps, config)):
            continue
        features = extract_panel_features(steps)
        if features['precredit_outflow_share'] == 0 and assess_panel(features)['target_probability'] < .1:
            low += 1
    assert low >= 10
