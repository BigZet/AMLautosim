import json

import pytest

from src.aml_workshop_simulator.services.aml_pattern_quality import quality_failures
from src.aml_workshop_simulator.services.aml_pattern_model import AMLPatternModel


def result(share):
    return dict(
        agreement=0.99,
        grey_row_share=share,
        pattern_share_among_low=0.01,
        nonpattern_share_among_high=0.01,
    )


@pytest.mark.parametrize("share", [0, 0.0999, 0.2001, 1, float("nan")])
def test_invalid_population_grey_share_rejected(share):
    assert quality_failures(result(share), representative=True)


@pytest.mark.parametrize("share", [0.10, 0.15, 0.20])
def test_requested_interval_includes_both_boundaries(share):
    assert quality_failures(result(share), representative=True) == []


def test_good_grey_share_does_not_hide_confident_errors():
    metrics = result(0.15)
    metrics["nonpattern_share_among_high"] = 0.2
    assert quality_failures(metrics, representative=True) == [
        "nonpattern_share_among_high"
    ]


def test_handpicked_examples_are_not_required_to_have_population_mix():
    assert quality_failures(result(0), representative=False) == []


def test_old_success_manifest_cannot_bypass_new_requirement(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps(dict(offline_quality_passed=True))
    )
    with pytest.raises(ValueError, match="obsolete quality criteria"):
        AMLPatternModel(tmp_path)
