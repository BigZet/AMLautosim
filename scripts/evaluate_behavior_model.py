"""Evaluate a frozen model; fitting is explicitly forbidden in this process."""

import argparse
from unittest.mock import patch
from catboost import CatBoostRegressor
from scripts.behavior_model import evaluate

if __name__ == "__main__":
    p = argparse.ArgumentParser(__doc__)
    p.add_argument("--dataset", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    with patch.object(
        CatBoostRegressor, "fit", side_effect=AssertionError("Evaluation must not fit")
    ):
        evaluate(args.dataset, args.model, args.output)
