# Saved API result contracts

Captured 2026-09-17 from actual FastAPI `GET /api/v1/rounds/current/state`
responses after submission and scoring against a disposable PostgreSQL database.
Files contain the unedited `result` object, not authentication data or live players.

- `result-v3.json`: `test_model_round_atomic_retry_and_no_early_explanation`,
  existing v8 package and native CatBoost/SHAP.
- `result-v4.json`: `test_probability_atomic_retry_storage_and_completed_reads`,
  v10 test-only runtime fixture. Repeated-letter model hashes are test identities.
  This captures API serialization, persistence and the 0.09999 boundary; it is
  **not** a production classifier prediction or release acceptance evidence.

The capture run also executed `test_modified_pin_fails_atomically`: 3 passed.
`tests/unit/test_scoring_api_fixtures.py` checks discriminated parsing and exact
probability preservation. Native binary-model/SHAP behavior is tested separately
in `tests/ml/test_aml_probability_model.py`.
