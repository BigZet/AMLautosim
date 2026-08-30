"""Human-readable rendering of one stored step.

The administrator inspector must show *every* parameter a step carries — a
`false`, a `0` and a value that happens to equal the default are all real data
and none of them may be dropped. The mapping from raw value to label lives here
so the API can hand the UI a finished structure instead of every client
re-deriving the card metadata.
"""

from __future__ import annotations

from typing import Any

from aml_workshop_simulator.domain.action_parameters import (
    CONTEXT_FIELDS,
    context_value_label,
    option_label,
)
from aml_workshop_simulator.domain.channels import channel_label
from aml_workshop_simulator.domain.round_policy import (
    PARAM_CHANNEL,
    OperationPolicy,
    action_param,
    context_param,
)
from aml_workshop_simulator.domain.rules import CardSpec, money

CONTEXT_ORDER = (
    "recipient_type",
    "time_of_day",
    "velocity",
    "has_documents",
)


def _row(
    param: str,
    label: str,
    value: Any,
    display: str,
    source: str,
    editable: bool,
) -> dict[str, Any]:
    return {
        "param": param,
        "label": label,
        "value": value,
        "display": display,
        "source": source,
        "editable": editable,
    }


def parameter_rows(
    step: dict[str, Any],
    spec: CardSpec | None,
    operation: OperationPolicy | None = None,
) -> list[dict[str, Any]]:
    """Every parameter of one step, labelled, in a stable display order."""
    context = dict(step.get("context") or {})
    details = dict(step.get("action_details") or {})
    rows: list[dict[str, Any]] = []

    channel = context.get("channel")
    rows.append(
        _row(
            PARAM_CHANNEL,
            "Канал",
            channel,
            channel_label(str(channel)) if channel is not None else "—",
            "context",
            operation is None or operation.is_visible(PARAM_CHANNEL),
        )
    )

    declared_context = (
        {item["key"] for item in spec.context_fields} if spec is not None else set()
    )
    for key in CONTEXT_ORDER:
        if key not in context:
            continue
        param = context_param(key)
        field = CONTEXT_FIELDS.get(key, {})
        rows.append(
            _row(
                param,
                str(field.get("label", key)),
                context[key],
                context_value_label(key, context[key]),
                "context",
                bool(
                    key in declared_context
                    and (operation is None or operation.is_visible(param))
                ),
            )
        )

    declared_fields = {item["key"]: item for item in (spec.fields if spec else ())}
    for key in sorted(details):
        param = action_param(key)
        field = declared_fields.get(key)
        label = str(field["label"]) if field else key
        display = (
            option_label([field], key, details[key]) if field else str(details[key])
        )
        rows.append(
            _row(
                param,
                label,
                details[key],
                display,
                "action_details" if field else "unknown",
                bool(field and (operation is None or operation.is_visible(param))),
            )
        )
    return rows


def describe_step(
    step: dict[str, Any],
    index: int,
    spec: CardSpec | None,
    impact: dict[str, Any] | None = None,
    operation: OperationPolicy | None = None,
) -> dict[str, Any]:
    """One fully described step: identity, parameters, cost and resources."""
    card_ref = dict(step.get("card") or {})
    impact = dict(impact or {})
    before = dict(impact.get("resources_before") or {})
    after = dict(impact.get("resources_after") or {})

    return {
        "index": index,
        "step_id": str(step.get("step_id", "")),
        "card": {
            "id": card_ref.get("id"),
            "code": card_ref.get("code"),
            "version": card_ref.get("version"),
            "title": spec.title if spec else str(card_ref.get("code", "")),
            "category": spec.category if spec else None,
            "flow": spec.flow if spec else None,
            "requires_card_code": spec.requires_card_code if spec else None,
            "quota_category": spec.quota_category if spec else None,
        },
        "amount": f"{money(step.get('amount', 0)):.2f}",
        "frequency": int(step.get("frequency", 1)),
        "gross": impact.get("gross"),
        "fee": impact.get("fee"),
        "parameters": parameter_rows(step, spec, operation),
        "costs": {
            "money_delta": impact.get("money_delta"),
            "energy": impact.get("energy_cost"),
            "time": impact.get("time_cost"),
        },
        "resources_before": before,
        "resources_after": after,
        "detail_factors": impact.get("detail_factors") or [],
    }


def describe_chain(
    steps: list[dict[str, Any]],
    specs: dict[tuple[str, int], CardSpec],
    snapshot: dict[str, Any] | None = None,
    policy: Any = None,
) -> list[dict[str, Any]]:
    """Describe a whole stored chain against the card versions it references."""
    per_step = {
        str(item.get("step_id")): item
        for item in ((snapshot or {}).get("per_step") or [])
    }
    described: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        card_ref = dict(step.get("card") or {})
        key = (str(card_ref.get("code")), int(card_ref.get("version", 1)))
        operation = policy.for_card(key) if policy is not None else None
        described.append(
            describe_step(
                step,
                index,
                specs.get(key),
                per_step.get(str(step.get("step_id"))),
                operation,
            )
        )
    return described
