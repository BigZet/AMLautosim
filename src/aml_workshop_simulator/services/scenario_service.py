"""Server-side scenario orchestration.

The canonical chain always lives in PostgreSQL. Streamlit sends a full
replacement of the editable scenario; FastAPI normalises it against the round policy,
re-validates it against the immutable card versions pinned by the round
snapshot and stores the canonical form together with a freshly computed
resource snapshot.

Normalisation only ever *fills in* parameters the participant was not offered.
A hidden parameter that arrives with a value the round does not pin it to is
kept as sent, so `domain.rules` can reject it instead of silently repairing a
payload that no legal client could have produced.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any

from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.domain.round_policy import (
    PARAM_CHANNEL,
    OperationPolicy,
    RoundPolicy,
    action_param,
    context_param,
)
from src.aml_workshop_simulator.domain.rules import (
    CONTEXT_DEFAULTS,
    CardSpec,
    evaluate_scenario,
    money,
)
from src.aml_workshop_simulator.schemas.scenarios import ScenarioStepIn

CONTEXT_KEYS = ("recipient_type", "time_of_day", "velocity", "has_documents")


def load_round_card_specs(round_obj: Round) -> dict[tuple[str, int], CardSpec]:
    """Every current round contains a complete server-owned card snapshot."""
    from src.aml_workshop_simulator.services.configuration import snapshot_specs

    return snapshot_specs(round_obj.game_config)


def round_policy(
    round_obj: Round, specs: dict[tuple[str, int], CardSpec]
) -> RoundPolicy:
    return RoundPolicy.from_config(round_obj.game_config or {}, specs)


def _context_value(
    key: str,
    provided: Any,
    spec: CardSpec | None,
    operation: OperationPolicy | None,
) -> Any:
    if provided is not None:
        return provided
    if spec is None:
        return CONTEXT_DEFAULTS[key]
    param = context_param(key)
    declared = next((item for item in spec.context_fields if item["key"] == key), None)
    if declared is None:
        return spec.context_defaults[key]
    if operation is not None and not operation.is_visible(param):
        pinned = operation.default_for(param)
        return declared["default"] if pinned is None else pinned
    return declared["default"]


def _channel_value(
    provided: Any, spec: CardSpec | None, operation: OperationPolicy | None
) -> str:
    if provided is not None:
        return str(provided)
    if operation is not None and not operation.is_visible(PARAM_CHANNEL):
        pinned = operation.default_for(PARAM_CHANNEL)
        if pinned is not None:
            return str(pinned)
    if spec is not None and spec.channels:
        return str(spec.channels[0])
    return ""


def _action_details(
    provided: dict[str, Any],
    spec: CardSpec | None,
    operation: OperationPolicy | None,
) -> dict[str, Any]:
    details = {
        key: (str(value) if isinstance(value, Decimal) else value)
        for key, value in provided.items()
    }
    if spec is None or operation is None:
        return details
    # Only parameters the round hides are filled in. A visible required field
    # that the client did not send stays missing, so `domain.rules` reports
    # `missing_action_parameter` instead of the server inventing a value.
    for declared in spec.fields:
        key = declared["key"]
        if key in details:
            continue
        param = action_param(key)
        if operation.is_visible(param):
            continue
        pinned = operation.default_for(param)
        details[key] = declared["default"] if pinned is None else pinned
    return details


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
        key = (step.card.code, step.card.version)
        spec = specs.get(key)
        operation = policy.for_card(key) if policy is not None else None

        context = {
            name: _context_value(name, getattr(step.context, name), spec, operation)
            for name in CONTEXT_KEYS
        }
        context["channel"] = _channel_value(step.context.channel, spec, operation)
        canonical.append(
            {
                "step_id": str(step.step_id),
                "card": {
                    "id": step.card.id,
                    "code": step.card.code,
                    "version": step.card.version,
                },
                "amount": f"{money(step.amount):.2f}",
                "context": {
                    "recipient_type": context["recipient_type"],
                    "time_of_day": context["time_of_day"],
                    "velocity": context["velocity"],
                    "channel": context["channel"],
                    "has_documents": bool(context["has_documents"]),
                },
                "action_details": dict(
                    sorted(
                        _action_details(step.action_details, spec, operation).items()
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
    return evaluate_scenario(steps, card_specs, game_config, policy)


def prepare_scenario(
    round_obj: Round, steps: list[ScenarioStepIn]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    specs = load_round_card_specs(round_obj)
    policy = round_policy(round_obj, specs)
    canonical = canonical_steps(steps, specs, policy)
    return canonical, checked_snapshot(canonical, specs, round_obj.game_config, policy)


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
