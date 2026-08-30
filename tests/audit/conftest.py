"""Фикстуры аудиторского набора.

Повторяют доменные фикстуры `tests/unit/conftest.py`, чтобы не менять
существующие файлы: pytest не наследует фикстуры между соседними каталогами.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.aml_workshop_simulator.domain.catalog import CARD_CATALOG
from src.aml_workshop_simulator.domain.rules import (
    REFERENCE_GAME_CONFIG,
    CardSpec,
    card_spec_from_catalog,
    specs_by_key,
)


@pytest.fixture(scope="session")
def specs() -> dict[tuple[str, int], CardSpec]:
    return specs_by_key(
        card_spec_from_catalog(entry, index)
        for index, entry in enumerate(CARD_CATALOG, start=1)
    )


@pytest.fixture(scope="session")
def spec_by_code(specs: dict[tuple[str, int], CardSpec]) -> dict[str, CardSpec]:
    return {spec.code: spec for spec in specs.values()}


@pytest.fixture(scope="session")
def game_config() -> dict[str, Any]:
    """Снимок со всеми операциями и всеми параметрами, доступными участнику."""
    legacy = {
        key: value
        for key, value in REFERENCE_GAME_CONFIG.items()
        if key != "operations"
    }
    legacy["schema_version"] = 2
    return legacy
