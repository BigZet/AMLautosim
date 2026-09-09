from __future__ import annotations

from src.aml_workshop_simulator.db.models.action_cards import ActionCard
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.domain.channels import channel_label
from src.aml_workshop_simulator.domain.round_policy import (
    OperationPolicy,
    split_param,
)
from src.aml_workshop_simulator.domain.rules import (
    CardSpec,
    card_spec_from_row,
    submit_blockers,
)
from src.aml_workshop_simulator.schemas.rounds import (
    ActionCardOut,
    VisibleParamOut,
)
from src.aml_workshop_simulator.schemas.scenarios import (
    ScenarioOut,
)


def visible_param_out(spec: CardSpec, param: str) -> VisibleParamOut | None:
    field = spec.field_spec(param)
    if field is None:
        return None
    namespace, key = split_param(param)
    return VisibleParamOut(
        param=param,
        key=key,
        namespace=namespace,
        label=str(field.get("label", key)),
        kind=str(field.get("kind", "select")),
        help=field.get("help"),
        default=field.get("default"),
        options=[dict(option) for option in field.get("options", [])],
    )


def card_out(
    row: ActionCard | CardSpec, operation: OperationPolicy | None = None
) -> ActionCardOut:
    spec = row if isinstance(row, CardSpec) else card_spec_from_row(row)
    if operation is not None:
        spec = spec.with_overrides(operation.overrides)
        params = operation.visible_params
        pinned = dict(operation.pinned)
    else:
        params = spec.default_visible_params
        pinned = {}
    visible = [
        rendered
        for rendered in (visible_param_out(spec, param) for param in params)
        if rendered is not None
    ]
    return ActionCardOut(
        id=spec.id,
        code=spec.code,
        version=spec.version,
        title=spec.title,
        description=spec.description,
        category=spec.category,
        flow=spec.flow,
        risk_weight=str(spec.risk_weight),
        costs={
            "energy": spec.energy_cost,
            "time": spec.time_cost,
        },
        fee_rate=str(spec.fee_rate),
        min_amount=str(spec.min_amount),
        max_amount=str(spec.max_amount),
        max_occurrences=spec.max_occurrences,
        requires_card_code=spec.requires_card_code,
        quota_category=spec.quota_category,
        channels=list(spec.channels),
        channel_labels={item: channel_label(item) for item in spec.channels},
        fields=[dict(item) for item in spec.fields],
        context_fields=[dict(item) for item in spec.context_fields],
        visible_params=visible,
        pinned_defaults=pinned,
    )


def scenario_out(scenario: Scenario) -> ScenarioOut:
    editing = scenario.status == "editing"
    blockers = submit_blockers(scenario.resource_snapshot) if editing else []
    return ScenarioOut(
        id=scenario.id,
        round_id=scenario.round_id,
        participant_id=scenario.participant_id,
        status=scenario.status,
        revision=scenario.revision,
        steps=scenario.steps,
        resources=scenario.resource_snapshot or {},
        updated_at=scenario.updated_at,
        submitted_at=scenario.submitted_at,
        can_edit=editing,
        can_submit=editing and not blockers,
        blockers=blockers,
    )
