"""Generate metadata from the same configuration and validators as the API."""

from src.aml_workshop_simulator.core.game_config import LIMITS, load_config
from src.aml_workshop_simulator.domain.action_parameters import CONTEXT_FIELDS
from src.aml_workshop_simulator.domain.channels import ALL_CHANNELS
from src.aml_workshop_simulator.domain.round_policy import CARD_OVERRIDE_KEYS
from src.aml_workshop_simulator.domain.rules import QUOTA_LABELS
from src.aml_workshop_simulator.schemas.editor_metadata import (
    EditorMetadataOut,
    NumericOverrideOut,
)
from src.aml_workshop_simulator.schemas.game_config_validation import (
    SUPPORTED_LEADERBOARD,
    SUPPORTED_RULESETS,
    SUPPORTED_SCORING,
)
from src.aml_workshop_simulator.schemas.round_config import (
    RESOURCE_WEIGHT_KEYS,
    OperationIn,
)


def editor_metadata() -> EditorMetadataOut:
    labels = load_config("editor_labels.json")
    labels.update(
        {
            "initial_balance": "Начальный баланс",
            "initial_energy": "Начальная энергия",
            "initial_time": "Начальное время",
            "target_outflow": "Цель исходящих операций",
            "max_actions": "Максимум шагов",
            "max_identical_steps": "Повторения одной операции",
            "max_night_operations": "Ночные операции",
            "max_anonymous_operations": "Анонимные операции",
            "min_amount": "Минимальная сумма",
            "max_amount": "Максимальная сумма",
            "max_occurrences": "Максимум использований",
            "energy_cost": "Стоимость энергии",
            "fee_rate": "Комиссия (доля)",
            "risk_weight": "Базовый риск",
            "review_threshold": "Порог проверки",
            "suspicious_threshold": "Порог подозрения",
            "stealth": "Скрытность",
            "resources": "Ресурсы",
            "balance": "Баланс",
            "energy": "Энергия",
            "time": "Время",
            "fees": "Комиссии",
            "available_steps": "Доступные шаги",
        }
    )
    overrides = []
    for key in CARD_OVERRIDE_KEYS:
        field = OperationIn.model_fields[key]
        item = NumericOverrideOut(
            key=key,
            label=labels[key],
            integer=key in {"max_occurrences", "energy_cost", "time_cost"},
        )
        for constraint in field.metadata:
            for attr in ("ge", "gt", "le", "decimal_places"):
                value = getattr(constraint, attr, None)
                if value is None:
                    continue
                if attr in {"ge", "gt"}:
                    item.minimum = str(value)
                    item.exclusive_minimum = attr == "gt"
                elif attr == "le":
                    item.maximum = str(value)
                else:
                    item.decimal_places = value
        overrides.append(item)
    dictionary_keys = {"channel": list(ALL_CHANNELS)}
    for name, field in CONTEXT_FIELDS.items():
        if field.get("options"):
            dictionary_keys[name] = [o["value"] for o in field["options"]]
    from src.aml_workshop_simulator.core.config import settings

    return EditorMetadataOut(
        available_contracts=[10] if settings.EXPANDED_ROUNDS_ENABLED else [],
        version=1,
        schema_version=10,
        limits=LIMITS,
        labels=labels,
        quotas=QUOTA_LABELS,
        resource_weights={k: labels[k] for k in RESOURCE_WEIGHT_KEYS},
        supported_versions={
            "ruleset_version": sorted(SUPPORTED_RULESETS),
            "scoring": sorted(SUPPORTED_SCORING),
            "leaderboard": sorted(SUPPORTED_LEADERBOARD),
        },
        dictionary_keys=dictionary_keys,
        overrides=overrides,
    )
