"""Public game-engine facade used by the CatBoost adapter and shared callers."""

from .game_models import (
    MONEY,
    QUOTA_LABELS,
    REFERENCE_GAME_CONFIG,
    RULESET_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    ZERO,
    CardSpec,
    RoundRules,
    StructuralError,
    Violation,
    card_spec_from_catalog,
    card_spec_from_row,
    money,
)
from .simulation import (
    action_detail_effects,
    evaluate_scenario,
    specs_by_key,
    submit_blockers,
)
from .structure import resolve_policy, validate_structure

__all__ = [
    "MONEY",
    "QUOTA_LABELS",
    "REFERENCE_GAME_CONFIG",
    "RULESET_VERSION",
    "SNAPSHOT_SCHEMA_VERSION",
    "ZERO",
    "CardSpec",
    "RoundRules",
    "StructuralError",
    "Violation",
    "card_spec_from_catalog",
    "card_spec_from_row",
    "money",
    "action_detail_effects",
    "evaluate_scenario",
    "specs_by_key",
    "submit_blockers",
    "resolve_policy",
    "validate_structure",
]
