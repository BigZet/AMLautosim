"""
Script to generate sample training/validation datasets for CatBoost from AML scenarios.
This outputs both a CSV dataset and JSON dataset with full features and ground truth labels.
"""
from __future__ import annotations

import csv
import json
import os
import random
import sys
import uuid
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.aml_workshop_simulator.domain.catalog import CARD_CATALOG
from src.aml_workshop_simulator.domain.rules import (
    REFERENCE_GAME_CONFIG,
    card_spec_from_catalog,
    specs_by_key,
)
from src.aml_workshop_simulator.domain.scoring import score_scenario
from src.aml_workshop_simulator.services.catboost_features import (
    extract_catboost_features,
    get_catboost_categorical_feature_names,
    get_catboost_feature_names,
)

CARD_SPECS = specs_by_key(
    card_spec_from_catalog(entry, index)
    for index, entry in enumerate(CARD_CATALOG, start=1)
)
CARD_IDS = {spec.code: spec.id for spec in CARD_SPECS.values()}


def canonical(step: dict) -> dict:
    """Convert a generator step into the canonical scenario step format."""
    code = step["card_code"]
    context = {
        "country_risk": "low",
        "recipient_type": "known_counterparty",
        "time_of_day": "day",
        "velocity": "normal",
        "channel": "bank",
        "has_documents": True,
        **step.get("context", {}),
    }
    return {
        "step_id": str(uuid.uuid4()),
        "card": {"id": CARD_IDS[code], "code": code, "version": 1},
        "amount": f"{float(step['amount']):.2f}",
        "frequency": int(step["frequency"]),
        "context": context,
        "action_details": step.get("details", {}),
    }


def generate_synthetic_scenarios(n_samples: int = 250) -> list[dict]:
    """Generates realistic AML simulation scenarios for training data."""
    card_codes = [spec.code for spec in CARD_SPECS.values()]
    channels = ["bank", "mobile", "web", "atm", "branch", "exchange"]
    country_risks = ["low", "low", "low", "medium", "high"]
    recipient_types = ["known_counterparty", "known_counterparty", "new_counterparty", "anonymous_wallet"]
    times_of_day = ["day", "day", "evening", "night"]
    velocities = ["spaced", "normal", "normal", "rapid"]
    
    samples = []
    
    for i in range(n_samples):
        # Determine archetype: 0=benign retail, 1=smurfing/structuring, 2=rapid crypto evasion, 3=cross-border laundering
        archetype = random.choice(["retail", "smurfing", "crypto_evasion", "cross_border"])
        n_steps = random.randint(2, 8)
        steps = []
        
        if archetype == "retail":
            steps.append({
                "card_code": "salary",
                "amount": random.choice([50000, 80000, 120000]),
                "frequency": 1,
                "context": {"channel": "bank", "country_risk": "low", "recipient_type": "known_counterparty", "time_of_day": "day", "velocity": "spaced", "has_documents": True},
                "details": {"employer_profile": "verified_employer", "income_basis": "payroll_registry"}
            })
            for _ in range(n_steps - 1):
                steps.append({
                    "card_code": random.choice(["card_transfer", "online_purchase"]),
                    "amount": random.randint(3000, 40000),
                    "frequency": random.randint(1, 2),
                    "context": {"channel": random.choice(["mobile", "web"]), "country_risk": "low", "recipient_type": "known_counterparty", "time_of_day": "day", "velocity": "normal", "has_documents": True},
                    "details": {}
                })
        elif archetype == "smurfing":
            steps.append({
                "card_code": "cash_deposit",
                "amount": 30000,
                "frequency": 3,
                "context": {"channel": "atm", "country_risk": "low", "recipient_type": "known_counterparty", "time_of_day": "night", "velocity": "rapid", "has_documents": False},
                "details": {"funds_source": "unexplained", "deposit_pattern": "several_atms"}
            })
            for _ in range(n_steps - 1):
                steps.append({
                    "card_code": "card_transfer",
                    "amount": 29000,
                    "frequency": 1,
                    "context": {"channel": "mobile", "country_risk": "low", "recipient_type": "new_counterparty", "time_of_day": "night", "velocity": "rapid", "has_documents": False},
                    "details": {"transfer_purpose": "no_purpose", "recipient_relationship": "unknown"}
                })
        elif archetype == "crypto_evasion":
            steps.append({
                "card_code": "cash_deposit",
                "amount": 100000,
                "frequency": 1,
                "context": {"channel": "atm", "country_risk": "low", "recipient_type": "known_counterparty", "time_of_day": "evening", "velocity": "rapid", "has_documents": False},
                "details": {"funds_source": "borrowed_cash", "deposit_pattern": "third_party"}
            })
            steps.append({
                "card_code": "crypto_exchange",
                "amount": 95000,
                "frequency": 1,
                "context": {"channel": "exchange", "country_risk": "high", "recipient_type": "anonymous_wallet", "time_of_day": "night", "velocity": "rapid", "has_documents": False},
                "details": {"platform_profile": "unknown_service", "wallet_owner": "third_party_wallet", "asset_profile": "privacy_asset"}
            })
        else: # cross_border
            steps.append({
                "card_code": "salary",
                "amount": 150000,
                "frequency": 1,
                "context": {"channel": "bank", "country_risk": "low", "recipient_type": "known_counterparty", "time_of_day": "day", "velocity": "normal", "has_documents": True},
                "details": {"employer_profile": "small_business", "income_basis": "service_contract"}
            })
            steps.append({
                "card_code": "international",
                "amount": 140000,
                "frequency": 1,
                "context": {"channel": "web", "country_risk": "high", "recipient_type": "new_counterparty", "time_of_day": "evening", "velocity": "rapid", "has_documents": False},
                "details": {"transfer_purpose": "investment", "payment_route": "fintech_gateway"}
            })

        # Ground truth from the versioned ruleset
        steps = [canonical(step) for step in steps]
        scored = score_scenario(steps, CARD_SPECS, REFERENCE_GAME_CONFIG)
        risk_score = float(scored["risk_score"])
        risk_label = scored["risk_label"]

        features = extract_catboost_features(steps)
        features["target_risk_score"] = risk_score
        features["target_risk_label"] = risk_label.value
        features["target_is_suspicious"] = 1 if risk_score >= 50.0 else 0
        features["scenario_archetype"] = archetype
        
        samples.append({
            "scenario_id": f"scen_{i+1:04d}",
            "archetype": archetype,
            "steps": steps,
            "features": features,
        })
        
    return samples


def main() -> None:
    output_dir = Path(__file__).resolve().parent.parent / "resources" / "catboost_sample_data"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    samples = generate_synthetic_scenarios(300)
    
    # 1. Save JSON with full steps and features
    json_path = output_dir / "catboost_training_dataset.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(samples, f, ensure_ascii=False, indent=2)
    print(f"[OK] Saved JSON dataset: {json_path}")
    
    # 2. Save Tabular CSV for direct CatBoost training
    csv_path = output_dir / "catboost_features_dataset.csv"
    feature_keys = list(samples[0]["features"].keys())
    
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["scenario_id"] + feature_keys)
        writer.writeheader()
        for s in samples:
            row = {"scenario_id": s["scenario_id"], **s["features"]}
            writer.writerow(row)
    print(f"[OK] Saved CSV features dataset: {csv_path}")
    
    # 3. Create a README explaining CatBoost training on these features
    readme_path = output_dir / "README.md"
    readme_content = f"""# CatBoost Dataset and Integration Spec for AML Simulator

This directory contains the feature extraction pipeline and ready-to-train sample datasets for CatBoost ML models.

## Dataset Files
- `catboost_features_dataset.csv`: Tabular matrix of {len(samples)} scenarios containing all extracted features + targets.
- `catboost_training_dataset.json`: Full scenarios (with raw steps and contexts) mapped to their CatBoost feature vectors.

## Extracted Features

### Numerical Features ({len(get_catboost_feature_names()) - len(get_catboost_categorical_feature_names())} features)
- Financial aggregates: `total_turnover`, `total_inflow`, `total_outflow`, `net_turnover`, `outflow_to_inflow_ratio`, `fees_total`, `fees_ratio`
- Channel/Channel category breakdowns: `cash_inflow_sum`, `cash_outflow_sum`, `cash_turnover_ratio`, `crypto_outflow_sum`, `crypto_turnover_ratio`, `international_outflow_sum`, `international_turnover_ratio`
- Risk & Behavioral signals: `high_risk_country_turnover`, `high_risk_country_ratio`, `anonymous_recipient_turnover`, `anonymous_recipient_ratio`, `night_operations_count`, `night_operations_ratio`, `rapid_velocity_count`, `rapid_velocity_ratio`, `without_docs_large_sum`, `without_docs_ratio`
- Statistical amounts: `avg_step_amount`, `max_step_amount`, `std_step_amount`, `max_frequency_single_step`
- Sequential patterns: `repeated_amount_count`, `rapid_credit_to_debit_count`, `cash_to_crypto_seq_flag`
- Indicator flags: `has_crypto`, `has_cash`, `has_international`, `num_steps`, `unique_channels_count`, `unique_cards_count`

### Categorical Features
`{get_catboost_categorical_feature_names()}`:
- `primary_channel` (e.g., 'mobile', 'web', 'atm', 'branch', 'exchange')
- `primary_category` (e.g., 'salary', 'cash', 'crypto', 'international', 'transfer', 'purchase')
- `most_frequent_card` (e.g., 'crypto_exchange', 'cash_deposit', 'salary', ...)

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

cat_features = {get_catboost_categorical_feature_names()}
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
"""
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme_content)
    print(f"[OK] Saved CatBoost integration README: {readme_path}")


if __name__ == "__main__":
    main()
