# CatBoost Dataset and Integration Spec for AML Simulator

This directory contains the feature extraction pipeline and synthetic integration examples for CatBoost ML models.

These are reproducible pipeline fixtures, not real AML observations or calibrated labels.
Targets come from the temporary rules, not independent ground truth. Each JSON example
includes `evaluation`: some chains exceed game limits or miss the objective. All steps
pass the current card structure contract; one card means one transaction (no frequency).
Regenerate with `python -m scripts.generate_catboost_sample_data` after config changes.

## Dataset Files
- `catboost_features_dataset.csv`: Tabular matrix of 300 scenarios containing all extracted features + targets.
- `catboost_training_dataset.json`: Full scenarios (with raw steps and contexts) mapped to their CatBoost feature vectors.

## Extracted Features

### Numerical Features (32 features)
- Financial aggregates: `total_turnover`, `total_inflow`, `total_outflow`, `net_turnover`, `outflow_to_inflow_ratio`, `fees_total`, `fees_ratio`
- Incoming transfers: `incoming_transfer_sum`, `incoming_transfer_count`, `crypto_exchange_inflow_sum`, `foreign_bank_inflow_sum`
- Cash breakdowns: `cash_inflow_sum`, `cash_outflow_sum`, `cash_turnover_ratio`
- Risk & Behavioral signals: `anonymous_recipient_turnover`, `anonymous_recipient_ratio`, `night_operations_count`, `night_operations_ratio`, `rapid_velocity_count`, `rapid_velocity_ratio`, `without_docs_large_sum`, `without_docs_ratio`
- Statistical amounts: `avg_step_amount`, `max_step_amount`, `std_step_amount`, `max_frequency_single_step`
- Sequential patterns: `repeated_amount_count`, `rapid_credit_to_debit_count`
- Indicator flags: `has_cash`, `num_steps`, `unique_channels_count`, `unique_cards_count`

### Categorical Features
`['primary_channel', 'primary_category', 'most_frequent_card', 'primary_incoming_source', 'primary_sender_relationship']`:
- `primary_channel` (e.g., 'mobile', 'web', 'atm', 'branch')
- `primary_category` (`salary`, `cash`, `transfer`, `incoming_transfer`)
- `most_frequent_card` (`salary`, `incoming_transfer`, `card_transfer`, `cash_withdrawal`)

- `primary_incoming_source`: `domestic_bank`, `foreign_bank_kg`, `crypto_exchange`, `payment_service`, or `none`
- `primary_sender_relationship`: `anonymous_new_account`, `anonymous_established_account`, `regular_sender`, or `none`

The incoming channel is `bank`: sources describe provenance, not cash or a UI channel.
Crypto values represent bank credits after selling assets, in RUB equivalent. Source
coefficients are fictional workshop settings, not country or institution ratings.
New source features change the feature schema; regenerate data and retrain future models.

### Target Variables
- `target_risk_score`: Continuous risk score (0.0 to 100.0) -> for `CatBoostRegressor(loss_function='RMSE')`
- `target_is_suspicious`: Binary flag (0 / 1) -> for `CatBoostClassifier(loss_function='Logloss')`
- `target_risk_label`: Multi-class string ('normal', 'review', 'suspicious') -> for `CatBoostClassifier(loss_function='MultiClass')`

## CatBoost Training Quickstart

```python
import pandas as pd
from catboost import CatBoostRegressor, Pool
from sklearn.model_selection import train_test_split

# Load dataset
df = pd.read_csv("catboost_features_dataset.csv")

cat_features = ['primary_channel', 'primary_category', 'most_frequent_card', 'primary_incoming_source', 'primary_sender_relationship']
ignore_cols = ["scenario_id", "target_risk_score", "target_risk_label", "target_is_suspicious", "scenario_archetype"]
X = df.drop(columns=ignore_cols)
y = df["target_risk_score"]

X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)

train_pool = Pool(X_train, y_train, cat_features=cat_features)
val_pool = Pool(X_val, y_val, cat_features=cat_features)

model = CatBoostRegressor(iterations=500, learning_rate=0.05, depth=6, eval_metric="RMSE")
model.fit(train_pool, eval_set=val_pool, early_stopping_rounds=30, verbose=50)

# Save model for simulator inference
model.save_model("aml_catboost_model.cbm")
```
