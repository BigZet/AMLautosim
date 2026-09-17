"""The demo CLI must not promote a real tiny offline candidate."""

import pytest

from tests.ml.test_aml_probability_model import candidate, observations  # noqa: F401


def test_demo_inputs_reject_real_unreleased_package_before_dataset_access(
    candidate,  # noqa: F811
    tmp_path,
):
    from scripts.create_aml_demo import load_inputs

    with pytest.raises(ValueError, match="release gates"):
        load_inputs(
            tmp_path / "missing-dataset", candidate[0], tmp_path / "missing-demo"
        )
