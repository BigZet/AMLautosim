from scripts.generate_aml_review_ui import project_case
from scripts.check_expanded_balance import demo_config, demo_steps
from scripts.aml_dataset.expanded import record


def test_blind_projection_omits_targets_explanations_and_baseline():
    config = demo_config()
    row = record("review-ui", demo_steps(config), config)
    blind = project_case(row, blind=True)
    assert set(blind) == {"id", "observable_hash", "steps", "resources", "totals",
                          "behavior", "initial_resources", "timeline", "selection"}
    assert "target" not in blind and "explanation" not in blind
    assert "baseline" not in blind and "features" not in blind
    assert len(blind["timeline"]) == len(row["steps"])
    pilot = project_case(row, reason="risk_range")
    assert pilot["target"] == row["target_risk_score"]
    assert pilot["explanation"] == row["explanation"]


def test_review_projection_does_not_modify_source():
    config = demo_config()
    row = record("review-ui", demo_steps(config), config)
    before = repr(row)
    project_case(row, blind=True)
    assert repr(row) == before
