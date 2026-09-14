"""Run the real evaluation CLI with every CatBoost fit call forbidden.

Pass the same arguments as scripts.evaluate_aml_catboost. This is a full saved
model integration check, not part of the quick pytest suite.
"""

from unittest.mock import patch

from catboost import CatBoostRegressor
from scripts.evaluate_aml_catboost import main

if __name__ == "__main__":
    with patch.object(
        CatBoostRegressor,
        "fit",
        side_effect=AssertionError("Evaluation attempted to train"),
    ):
        main()
    print("EVALUATION-ONLY CHECK PASS: no fit calls", flush=True)
