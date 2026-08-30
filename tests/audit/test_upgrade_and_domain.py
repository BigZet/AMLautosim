"""Аудиторские проверки домена и пути обновления.

Каждый тест фиксирует поведение, найденное независимой ревизией. Там, где тест
закрепляет дефект, docstring говорит об этом прямо: после исправления такой тест
обязан упасть, и это ожидаемый сигнал.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from src.aml_workshop_simulator.domain.rules import (
    REFERENCE_GAME_CONFIG,
    evaluate_scenario,
    specs_by_key,
)
from src.aml_workshop_simulator.services.configuration import freeze_game_config
from tests.unit.conftest import make_step


# --------------------------------------------------------------------------
# A-1. Обновление установки: снимок раунда нельзя заморозить
# --------------------------------------------------------------------------


class _Row:
    """Минимальная строка `action_cards`, какой её видит `card_spec_from_row`."""

    def __init__(self, spec) -> None:
        self.id = spec.id
        self.code = spec.code
        self.version = spec.version
        self.title = spec.title
        self.category = spec.category
        self.flow = spec.flow
        self.risk_weight = spec.risk_weight
        self.energy_cost = spec.energy_cost
        self.time_cost = spec.time_cost
        self.fee_rate = spec.fee_rate
        self.min_amount = spec.min_amount
        self.max_amount = spec.max_amount
        self.max_frequency = spec.max_frequency
        self.requires_card_code = spec.requires_card_code
        self.parameter_schema = {
            "channels": list(spec.channels),
            "round_frequency_limit": spec.round_frequency_limit,
            "quota_category": spec.quota_category,
            "description": spec.description,
            "context_fields": [dict(item) for item in spec.context_fields],
            "fields": [dict(item) for item in spec.fields],
            "default_visible_params": list(spec.default_visible_params),
            "default_show_frequency": spec.default_show_frequency,
        }
        self.is_active = True


def test_freeze_game_config_rejects_a_round_that_references_a_removed_card(specs):
    """Дефект: раунд, созданный до сокращения каталога, больше не замораживается.

    `scripts.seed_database.seed_cards` вызывает `freeze_game_config` для каждого
    существующего раунда при каждом старте API. Если в снимке раунда остался код
    операции, которого больше нет в `action_cards`, функция бросает ValueError,
    seed завершается ненулевым кодом и uvicorn не стартует.
    """
    rows = [_Row(spec) for spec in specs.values()]
    config = {
        key: value
        for key, value in REFERENCE_GAME_CONFIG.items()
        if key != "card_snapshots"
    }
    config["operations"] = [
        *config["operations"],
        {"code": "international", "version": 1, "visible_params": [], "show_frequency": False},
    ]

    with pytest.raises(ValueError, match="a referenced card is missing"):
        freeze_game_config(config, rows)


def test_freeze_game_config_succeeds_once_a_snapshot_exists(specs):
    """Контроль: раунд с уже записанным `card_snapshots` не перепроверяется."""
    rows = [_Row(spec) for spec in specs.values()]
    frozen = freeze_game_config(dict(REFERENCE_GAME_CONFIG), rows)
    assert frozen["card_snapshots"], "снимок карточек должен быть записан"

    frozen["operations"] = [
        *frozen["operations"],
        {"code": "international", "version": 1, "visible_params": [], "show_frequency": False},
    ]
    # Повторная заморозка уже замороженного раунда не падает.
    assert freeze_game_config(frozen, rows)["card_snapshots"] == frozen["card_snapshots"]


# --------------------------------------------------------------------------
# A-2. Квота «anonymous» учитывается дважды
# --------------------------------------------------------------------------


def test_anonymous_quota_is_counted_twice_for_an_anonymous_category_card(
    spec_by_code, game_config
):
    """Дефект (латентный): оборот попадает в квоту `anonymous` два раза.

    `evaluate_scenario` сначала прибавляет `gross` к квоте карточки
    (`spec.quota_category`), затем безусловно прибавляет тот же `gross` к квоте
    `anonymous`, если получатель — анонимный кошелёк. Для карточки с
    `quota_category = "anonymous"` это удваивает использование квоты.

    В поставляемом `config/operations.json` такой карточки нет, поэтому дефект
    сейчас не проявляется; схема `CardConfig.quota_category` значение
    `"anonymous"` допускает.
    """
    anonymous_card = replace(spec_by_code["card_transfer"], quota_category="anonymous")
    specs = specs_by_key([anonymous_card])
    config = dict(game_config)
    config["constraints"] = {
        **config["constraints"],
        "category_limits": {"anonymous": "1000000.00"},
    }

    step = make_step(
        anonymous_card,
        Decimal("10000.00"),
        context={"recipient_type": "anonymous_wallet"},
    )
    snapshot = evaluate_scenario([step], specs, config)

    assert snapshot["limit_usage"]["anonymous"] == "20000.00"  # ожидалось 10000.00


def test_anonymous_quota_is_counted_once_when_the_card_has_no_category(
    spec_by_code, specs, game_config
):
    """Контроль: у поставляемой карточки квота считается один раз."""
    config = dict(game_config)
    config["constraints"] = {
        **config["constraints"],
        "category_limits": {"anonymous": "1000000.00"},
    }
    step = make_step(
        spec_by_code["card_transfer"],
        Decimal("10000.00"),
        context={"recipient_type": "anonymous_wallet"},
    )
    snapshot = evaluate_scenario([step], specs, config)
    assert snapshot["limit_usage"]["anonymous"] == "10000.00"


# --------------------------------------------------------------------------
# A-3. Веса ресурсов сравниваются точно
# --------------------------------------------------------------------------


def test_resource_weights_must_sum_to_exactly_one():
    """Сумма весов проверяется точным сравнением Decimal.

    Редактор админки (`ui/admin/config_editor.py:_number`) получает веса через
    `st.number_input(value=float(...))` и сериализует их как `str(float)`.
    Собственная проверка редактора допускает погрешность 1e-9, а API — нет.
    """
    from pydantic import ValidationError

    from src.aml_workshop_simulator.schemas.round_config import LeaderboardIn

    ok = LeaderboardIn.model_validate(
        {
            "version": "leaderboard-v2",
            "weights": {"stealth": "0.60", "resources": "0.40"},
            "resource_weights": {
                "balance": "0.27",
                "energy": "0.20",
                "time": "0.20",
                "fees": "0.20",
                "available_steps": "0.13",
            },
        }
    )
    assert ok.version == "leaderboard-v2"

    drifted = str(0.30000000000000004)
    with pytest.raises(ValidationError):
        LeaderboardIn.model_validate(
            {
                "version": "leaderboard-v2",
                "weights": {"stealth": "0.60", "resources": "0.40"},
                "resource_weights": {
                    "balance": drifted,
                    "energy": "0.20",
                    "time": "0.20",
                    "fees": "0.17",
                    "available_steps": "0.13",
                },
            }
        )
