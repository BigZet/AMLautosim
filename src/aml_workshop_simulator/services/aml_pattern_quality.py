"""Explicit acceptance criteria for the educational-pattern model."""

import math

QUALITY_POLICY = {
    "version": "pattern-quality-v2",
    "grey_probability_low_inclusive": 0.1,
    "grey_probability_high_exclusive": 0.9,
    "population_grey_share_min": 0.10,
    "population_grey_share_max": 0.20,
    "minimum_agreement": 0.95,
    "maximum_confident_error": 0.05,
    "grey_denominator": "unweighted held-out chain rows, not selected demonstrations",
}


def quality_failures(metrics, *, representative):
    failures = []

    def finite(value):
        return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1

    agreement = metrics.get("agreement")
    if not finite(agreement) or agreement < QUALITY_POLICY["minimum_agreement"]:
        failures.append("insufficient_pattern_agreement")
    for field in ("pattern_share_among_low", "nonpattern_share_among_high"):
        value = metrics.get(field)
        if value is not None and (
            not finite(value) or value > QUALITY_POLICY["maximum_confident_error"]
        ):
            failures.append(field)
    if representative:
        share = metrics.get("grey_row_share")
        if not finite(share) or not (
            QUALITY_POLICY["population_grey_share_min"]
            <= share
            <= QUALITY_POLICY["population_grey_share_max"]
        ):
            failures.append("population_grey_share_outside_10_to_20_percent")
    return failures
