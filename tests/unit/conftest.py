"""Domain-only fixtures: no database, no network."""

from __future__ import annotations

import uuid
from decimal import Decimal
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
    return REFERENCE_GAME_CONFIG


def make_step(
    spec: CardSpec,
    amount: Decimal | str | int,
    frequency: int = 1,
    channel: str | None = None,
    context: dict[str, Any] | None = None,
    action_details: dict[str, Any] | None = None,
    step_id: str | None = None,
    card_id: int | None = None,
    card_code: str | None = None,
    card_version: int | None = None,
) -> dict[str, Any]:
    """Canonical step dict, defaulting every field the card declares."""
    ctx: dict[str, Any] = {
        "country_risk": "low",
        "recipient_type": "known_counterparty",
        "time_of_day": "day",
        "velocity": "normal",
        "channel": channel or spec.channels[0],
        "has_documents": True,
    }
    ctx.update(context or {})
    details = {field["key"]: field["default"] for field in spec.fields}
    details.update(action_details or {})
    return {
        "step_id": step_id or str(uuid.uuid4()),
        "card": {
            "id": card_id if card_id is not None else spec.id,
            "code": card_code or spec.code,
            "version": card_version if card_version is not None else spec.version,
        },
        "amount": Decimal(str(amount)),
        "frequency": frequency,
        "context": ctx,
        "action_details": details,
    }
