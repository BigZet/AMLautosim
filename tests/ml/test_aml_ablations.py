import pytest


def test_ablation_groups_are_frozen_disjoint_observable_feature_blocks():
    from scripts.aml_ablations import feature_blocks
    from src.aml_workshop_simulator.services.aml_dataset_features_v5 import (
        FEATURE_NAMES,
    )

    blocks = feature_blocks()
    behavioral, scoped = (
        blocks[n] for n in ("without_scoped_evidence", "scoped_context_only")
    )
    assert not set(behavioral) & set(scoped)
    assert set(behavioral) | set(scoped) == set(FEATURE_NAMES)
    assert "contradicted_credit_share" in scoped
    assert "expected_credit_excess_amount" in scoped
    assert "count_incoming_transfer" in behavioral
    assert "episode_recipient_hhi_mean" in behavioral


def test_real_ablation_models_use_only_train_and_fixed_selected_parameters():
    import pandas as pd
    from scripts.aml_ablations import fit_ablations
    from scripts.aml_dataset.aml_casebook import build_casebook
    from src.aml_workshop_simulator.services.aml_dataset_features_v5 import (
        FEATURE_NAMES,
        FEATURE_VERSION,
        CATEGORICAL_FEATURES,
        extract_features,
    )

    from src.aml_workshop_simulator.domain.operation_purposes import allowed_purposes

    # Use existing compatible cases; retired purposes remain rejected by runtime.
    rows = [
        r for r in build_casebook()
        if r["aml_label"] is not None
        and all(s["purpose_code"] in allowed_purposes(s) for s in r["public_snapshot"]["steps"])
    ][:8]
    frame = pd.DataFrame([extract_features(**r["public_snapshot"]) for r in rows])
    schema = {
        "version": FEATURE_VERSION,
        "features": FEATURE_NAMES,
        "types": {
            n: "categorical" if n in CATEGORICAL_FEATURES else "numeric"
            for n in FEATURE_NAMES
        },
    }
    models = fit_ablations(
        {"features": frame, "labels": [r["aml_label"] for r in rows]},
        schema,
        {"depth": 4, "l2_leaf_reg": 10, "trees": 8},
    )
    assert set(models) == {"without_scoped_evidence", "scoped_context_only"}
    for entry in models.values():
        assert entry["model"].tree_count_ == 8
        assert entry["model"].feature_names_ == entry["features"]
        assert entry["parameters"]["random_seed"] == 2026091601
        assert entry["parameters"]["thread_count"] == 4
    with pytest.raises(ValueError):
        fit_ablations(
            {"features": frame, "labels": [0] * len(frame)},
            schema,
            {"depth": 4, "l2_leaf_reg": 10, "trees": 8},
        )
