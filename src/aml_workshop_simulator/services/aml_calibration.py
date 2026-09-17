"""Numerical calibration runtime: JSON parameters only, no sklearn or pickle."""

import math

import numpy as np

LOW_THRESHOLD = 0.1
HIGH_THRESHOLD = 0.9


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Calibration parameters must be finite JSON numbers")
    return float(value)


def validate_calibrator(artifact: dict) -> None:
    if not isinstance(artifact, dict):
        raise ValueError("Calibration artifact must be an object")
    method = artifact.get("method")
    if method == "none":
        if set(artifact) != {"method"}:
            raise ValueError("Identity calibration has no fitted parameters")
    elif method == "sigmoid":
        if set(artifact) != {"method", "a", "b"}:
            raise ValueError("Sigmoid requires a and b only")
        if _number(artifact["a"]) <= 0:
            raise ValueError("Sigmoid slope must be positive")
        _number(artifact["b"])
    elif method == "isotonic":
        if set(artifact) != {"method", "x", "y", "interpolation"}:
            raise ValueError("Isotonic requires x/y knots and interpolation")
        x, y = artifact["x"], artifact["y"]
        if artifact["interpolation"] != "linear_clamped":
            raise ValueError("Unsupported isotonic interpolation")
        if (
            not isinstance(x, list)
            or not isinstance(y, list)
            or not x
            or len(x) != len(y)
        ):
            raise ValueError("Isotonic knots must be nonempty equally sized lists")
        for value in x + y:
            _number(value)
        if any(a >= b for a, b in zip(x, x[1:])):
            raise ValueError("Isotonic x knots must be strictly increasing")
        if any(a > b for a, b in zip(y, y[1:])) or any(v < 0 or v > 1 for v in y):
            raise ValueError("Isotonic y knots must be monotonic probabilities")
    else:
        raise ValueError("Unsupported calibration method")


def apply_calibrator(raw_margin, artifact: dict) -> np.ndarray:
    validate_calibrator(artifact)
    margin = np.asarray(raw_margin, dtype=np.float64)
    if not np.isfinite(margin).all():
        raise ValueError("Raw margins must be finite")
    method = artifact["method"]
    if method == "isotonic":
        x, y = (
            np.asarray(artifact["x"], dtype=float),
            np.asarray(artifact["y"], dtype=float),
        )
        if len(x) == 1:
            return np.full_like(margin, y[0])
        bounded = np.clip(margin, x[0], x[-1])
        left = np.clip(np.searchsorted(x, bounded, side="right") - 1, 0, len(x) - 2)
        lo, hi = x[left], x[left + 1]
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            span = hi - lo
            fraction = (bounded - lo) / span
            # Only an opposite-sign enormous interval can overflow the difference.
            # Halving that interval preserves its ratio without global rescaling,
            # which could collapse small, otherwise representable knot spacings.
            fraction = np.where(
                np.isfinite(span), fraction, (bounded / 2 - lo / 2) / (hi / 2 - lo / 2)
            )
        return y[left] + fraction * (y[left + 1] - y[left])
    if method == "sigmoid":
        with np.errstate(over="ignore", invalid="ignore"):
            margin = artifact["a"] * margin + artifact["b"]
        if not np.isfinite(margin).all():
            raise ValueError("Calibrated margin overflow")
    # Stable at both ends without clipping or artificially stretching probabilities.
    return np.exp(-np.logaddexp(0.0, -margin))


def probability_category(probability: float) -> str:
    value = _number(probability)
    if not 0 <= value <= 1:
        raise ValueError("Probability must lie in [0, 1]")
    return (
        "low"
        if value < LOW_THRESHOLD
        else "high"
        if value >= HIGH_THRESHOLD
        else "review"
    )
