from copy import deepcopy

from tests.aml_context_support import context_fixture


def test_feature_dictionary_matches_explicit_allowlist():
    import json
    from pathlib import Path
    from src.aml_workshop_simulator.services.aml_dataset_features_v5 import FEATURE_NAMES, extract_features

    config, steps = context_fixture()
    features = extract_features(steps, config)
    dictionary = json.loads(Path("config/model/aml-classifier-v1-feature-descriptions.json").read_text(encoding="utf-8"))
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES))
    assert list(features) == FEATURE_NAMES
    assert set(dictionary["features"]) == set(FEATURE_NAMES)
    assert dictionary["extractor"] == "aml-observable-v5.0"
    assert all(v["title"] and v["description"] for v in dictionary["features"].values())


def test_verified_coverage_respects_amounts_not_number_of_documents():
    from src.aml_workshop_simulator.services.aml_dataset_features_v5 import extract_features

    config, steps = context_fixture()
    f = extract_features(steps, config)
    assert f["explained_credit_amount"] == 100000
    assert f["explained_debit_amount"] == 50000
    assert f["explanation_credit_applicable"] == 1
    assert f["explanation_credit_share"] == 100000 / 230000


def test_renaming_id_entities_and_country_does_not_change_model_features():
    from src.aml_workshop_simulator.services.aml_dataset_features_v5 import extract_features

    config, steps = context_fixture()
    original = extract_features(steps, config)
    for p in config["behavior"]["counterparties"]:
        if p["id"] == "A":
            p["id"] = "renamed"
        p["name"] = "Different UI label"
    for event in config["behavior"]["history"]["operations"]:
        if event.get("counterparty_id") == "A":
            event["counterparty_id"] = "renamed"
    for fact in config["behavior"]["aml_context"]["facts"]:
        fact["counterparty_ids"] = ["renamed" if p == "A" else p for p in fact["counterparty_ids"]]
    for step in steps:
        for field in ("sender_id", "recipient_id"):
            if step.get(field) == "A":
                step[field] = "renamed"
        if step["action_details"].get("bank_country"):
            step["action_details"]["bank_country"] = "KG"
    assert extract_features(steps, config) == original


def test_unknown_history_is_not_confirmed_inactivity():
    from src.aml_workshop_simulator.services.aml_dataset_features_v5 import extract_features

    config, steps = context_fixture()
    config["behavior"]["history"]["operations"] = []
    observed = extract_features(steps, config)
    config["behavior"]["history"]["operations"] = None
    ctx = config["behavior"]["aml_context"]
    ctx.update(history_coverage="unknown", history_start=None, history_end=None)
    missing = extract_features(steps, config)
    assert observed["observed_inactivity"] == 1
    assert missing["observed_inactivity"] == 0
    assert missing["context_history_unknown"] == 1


def test_context_status_does_not_depend_on_probability_or_hidden_outcome():
    from src.aml_workshop_simulator.services.aml_dataset_features_v5 import extract_features

    config, steps = context_fixture()
    other = deepcopy(config)
    # Metadata outside the immutable behavior snapshot cannot become a feature.
    other["private_author_truth"] = {"aml_label": 1, "label_rationale": "secret"}
    assert extract_features(steps, config) == extract_features(steps, other)


def test_no_credit_has_nonapplicable_denominator_not_false_legitimacy():
    from src.aml_workshop_simulator.services.aml_dataset_features_v5 import extract_features

    config, steps = context_fixture()
    f = extract_features([steps[1]], config)
    assert f["explanation_credit_applicable"] == 0
    assert f["explanation_credit_share"] == 0


def test_expected_totals_only_compared_over_complete_matching_period():
    from src.aml_workshop_simulator.services.aml_dataset_features_v5 import extract_features

    config, steps = context_fixture()
    f = extract_features(steps, config)
    # A few minutes of a day cannot establish an excess/shortfall versus daily expectation.
    assert f["expected_volume_comparable"] == 0
    assert f["expected_credit_excess_ratio"] == 0


def test_episode_concentration_uses_only_observed_episode_parties():
    from src.aml_workshop_simulator.services.aml_dataset_features_v5 import extract_features

    config, steps = context_fixture()
    steps = steps[:3]
    steps[1]["amount"] = steps[2]["amount"] = "40000.00"
    steps[2]["recipient_id"] = "B"
    features = extract_features(steps, config)
    assert features["observed_episode_count"] == 1
    assert features["episode_recipient_hhi_mean"] == .5
    assert features["episode_sender_hhi_mean"] == 1
    assert features["episode_fan_in_max"] == 1
    assert features["episode_fan_out_max"] == 2
    assert features["episode_recipient_concentration_applicable"] == 1
    # A debit alone does not establish a matched incoming/outgoing episode.
    features = extract_features([steps[1]], config)
    assert features["observed_episode_count"] == 0
    assert features["episode_recipient_hhi_mean"] == 0
    assert features["episode_recipient_concentration_applicable"] == 0
