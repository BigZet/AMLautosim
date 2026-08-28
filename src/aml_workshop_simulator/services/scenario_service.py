"""Server-side scenario orchestration.

The canonical chain always lives in PostgreSQL. Streamlit sends a full
replacement of the draft; FastAPI re-validates it against the immutable card
versions pinned by the round snapshot and stores the canonical form together
with a freshly computed resource snapshot.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.db.models.action_cards import ActionCard
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.domain.rules import (
    CardSpec,
    card_spec_from_row,
    evaluate_scenario,
    money,
)
from src.aml_workshop_simulator.schemas.scenarios import ScenarioStepIn


async def load_round_card_specs(
    db: AsyncSession, round_obj: Round
) -> dict[tuple[str, int], CardSpec]:
    """Card versions pinned by the round snapshot.

    A round that has been activated always carries an explicit
    `game_config.card_versions` list; a draft round without one falls back to
    every active catalog version so an administrator can preview the round.
    """
    config = round_obj.game_config or {}
    refs = config.get("card_versions") or []
    if refs:
        pairs = {(str(ref["code"]), int(ref["version"])) for ref in refs}
        rows = (await db.execute(select(ActionCard))).scalars().all()
        specs = [
            card_spec_from_row(row) for row in rows if (row.code, row.version) in pairs
        ]
    else:
        rows = (
            (await db.execute(select(ActionCard).where(ActionCard.is_active)))
            .scalars()
            .all()
        )
        specs = [card_spec_from_row(row) for row in rows]
    return {spec.key: spec for spec in specs}


def canonical_steps(steps: list[ScenarioStepIn]) -> list[dict[str, Any]]:
    """Deterministic JSON-safe representation stored in `scenarios.steps`.

    The channel exists exactly once, inside `context`; there is no parallel flat
    field that could drift away from it.
    """
    canonical: list[dict[str, Any]] = []
    for step in steps:
        canonical.append(
            {
                "step_id": str(step.step_id),
                "card": {
                    "id": step.card.id,
                    "code": step.card.code,
                    "version": step.card.version,
                },
                "amount": f"{money(step.amount):.2f}",
                "frequency": step.frequency,
                "context": {
                    "country_risk": step.context.country_risk,
                    "recipient_type": step.context.recipient_type,
                    "time_of_day": step.context.time_of_day,
                    "velocity": step.context.velocity,
                    "channel": str(step.context.channel),
                    "has_documents": step.context.has_documents,
                },
                "action_details": {
                    key: (str(value) if isinstance(value, Decimal) else value)
                    for key, value in sorted(step.action_details.items())
                },
            }
        )
    return canonical


def payload_hash(steps: list[dict[str, Any]]) -> str:
    """Stable digest of the canonical steps; not a security hash."""
    blob = json.dumps(steps, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_snapshot(
    steps: list[dict[str, Any]],
    card_specs: dict[tuple[str, int], CardSpec],
    game_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Full resource snapshot for an already canonical chain."""
    return evaluate_scenario(steps, card_specs, game_config)
