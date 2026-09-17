"""Normalize declared context, preserving invalid input for structural rejection."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.domain.round_policy import RoundPolicy
from src.aml_workshop_simulator.domain.contract_versions import (
    contract_version,
    require_playable_contract,
)
from src.aml_workshop_simulator.core.errors import ValidationFailed
from src.aml_workshop_simulator.domain.rules import CardSpec, evaluate_scenario, money
from src.aml_workshop_simulator.schemas.scenarios import (
    ScenarioStepIn,
    ExpandedScenarioStepIn,
)


def load_round_card_specs(round_obj: Round) -> dict[tuple[str, int], CardSpec]:
    """Every current round contains a complete server-owned card snapshot."""
    from src.aml_workshop_simulator.services.configuration import snapshot_specs

    return snapshot_specs(round_obj.game_config)


def round_policy(
    round_obj: Round, specs: dict[tuple[str, int], CardSpec]
) -> RoundPolicy:
    return RoundPolicy.from_config(round_obj.game_config or {}, specs)


def canonical_steps(
    steps: list[ScenarioStepIn],
    specs: dict[tuple[str, int], CardSpec] | None = None,
    policy: RoundPolicy | None = None,
) -> list[dict[str, Any]]:
    """Deterministic JSON-safe representation stored in `scenarios.steps`.

    The channel exists exactly once, inside `context`; there is no parallel flat
    field that could drift away from it.
    """
    specs = specs or {}
    canonical: list[dict[str, Any]] = []
    for step in steps:
        if isinstance(step, ExpandedScenarioStepIn):
            raise ValidationFailed(
                "Шаг v8 неприменим к раунду v7.", code="scenario_contract_mismatch"
            )
        key = (step.card.code, step.card.version)
        spec = specs.get(key)
        # Preserve all explicitly supplied keys (including null) so a field
        # inapplicable to this card cannot disappear during normalization.
        context = step.context.model_dump(exclude_unset=True)
        if spec is not None:
            for declared in spec.context_fields:
                name = declared["key"]
                if context.get(name) is None:
                    context[name] = declared["default"]
            if spec.channels and context.get("channel") is None:
                context["channel"] = spec.channels[0]
        canonical.append(
            {
                "step_id": str(step.step_id),
                "card": {
                    "id": step.card.id,
                    "code": step.card.code,
                    "version": step.card.version,
                },
                "amount": f"{money(step.amount):.2f}",
                "context": context,
                "action_details": dict(
                    sorted(
                        (key, str(value) if isinstance(value, Decimal) else value)
                        for key, value in step.action_details.items()
                    )
                ),
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
    policy: RoundPolicy | None = None,
) -> dict[str, Any]:
    """Full resource snapshot for an already canonical chain."""
    if contract_version(game_config) in (8, 9, 10):
        from src.aml_workshop_simulator.services.expanded_simulation import (
            evaluate_expanded_scenario,
        )

        return evaluate_expanded_scenario(steps, game_config)
    return evaluate_scenario(steps, card_specs, game_config, policy)


def prepare_scenario(
    round_obj: Round, steps: list[ScenarioStepIn]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    require_playable_contract(round_obj.game_config)
    specs = load_round_card_specs(round_obj)
    policy = round_policy(round_obj, specs)
    canonical = canonical_round_steps(round_obj, steps, specs, policy)
    return canonical, checked_snapshot(canonical, specs, round_obj.game_config, policy)


def canonical_round_steps(round_obj, steps, specs, policy):
    if contract_version(round_obj.game_config) in (8, 9, 10):
        from src.aml_workshop_simulator.services.counterparties import (
            canonical_expanded_steps,
        )

        return canonical_expanded_steps(steps, round_obj.game_config)
    return canonical_steps(steps, specs, policy)


def checked_snapshot(steps, specs, config, policy) -> dict[str, Any]:
    from src.aml_workshop_simulator.core.errors import ValidationFailed
    from src.aml_workshop_simulator.domain.rules import StructuralError

    try:
        return build_snapshot(steps, specs, config, policy)
    except StructuralError as exc:
        violations = [item.as_dict() for item in exc.violations]
        raise ValidationFailed(
            violations[0]["message"], details={"violations": violations}
        ) from exc
