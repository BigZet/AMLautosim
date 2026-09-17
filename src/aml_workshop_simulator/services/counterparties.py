"""Resolve v8 identities solely against the immutable round snapshot.

This preparation layer does not calculate resources, time or AML scores.
"""

from collections import Counter

from pydantic import ValidationError

from src.aml_workshop_simulator.core.errors import ValidationFailed
from src.aml_workshop_simulator.domain.contract_versions import contract_version
from src.aml_workshop_simulator.domain.round_policy import RoundPolicy
from src.aml_workshop_simulator.schemas.expanded_contract import ExpandedBehavior
from src.aml_workshop_simulator.schemas.scenarios import ExpandedScenarioStepIn
from src.aml_workshop_simulator.services.configuration import snapshot_specs

from src.aml_workshop_simulator.domain.counterparty_roles import (
    PARTY_ROLES,
    party_allowed,
)


def behavior_for(config):
    if contract_version(config) == 10:
        from src.aml_workshop_simulator.services.aml_context import BehaviorV10
        return BehaviorV10.model_validate(config["behavior"])
    if contract_version(config) == 9:
        from src.aml_workshop_simulator.services.semantic_contract import BehaviorV9
        return BehaviorV9.model_validate(config["behavior"])
    if contract_version(config) != 8:
        raise ValidationFailed("Каталог сторон доступен только в контракте v8.")
    return ExpandedBehavior.model_validate(config["behavior"])


def fail(message, index, field):
    raise ValidationFailed(
        message,
        code="counterparty_contract_invalid",
        details={"step_index": index, "field": field},
    )


def canonical_expanded_steps(steps, config):
    """Validate snapshot/card/role references and return JSON-safe input only.

    Derived properties are deliberately not stored in steps or trusted on replay.
    Resource sufficiency and whole-chain limits belong to the future v8 engine.
    """
    if contract_version(config) == 10:
        from src.aml_workshop_simulator.services.aml_context import canonical_steps
        try:
            return canonical_steps(steps, config)
        except ValueError as error:
            raise ValidationFailed(str(error), code="aml_context_invalid") from error
    if contract_version(config) == 9:
        from src.aml_workshop_simulator.services.semantic_contract import canonical_steps
        try:
            return canonical_steps(steps, config)
        except ValueError as error:
            raise ValidationFailed(str(error), code="semantic_contract_invalid") from error
    behavior = behavior_for(config)
    parties = {party.id: party for party in behavior.counterparties}
    specs = snapshot_specs(config)
    policy = RoundPolicy.from_config(config, specs)
    result, seen = [], set()
    for index, raw in enumerate(steps, 1):
        try:
            step = ExpandedScenarioStepIn.model_validate(
                raw.model_dump(mode="json", exclude_unset=True)
                if hasattr(raw, "model_dump")
                else raw
            )
        except ValidationError as error:
            fail(str(error), index, "step")
        if step.step_id in seen:
            fail("Повторный ID шага.", index, "step_id")
        seen.add(step.step_id)
        key = (step.card.code, step.card.version)
        spec = specs.get(key)
        operation = policy.for_card(key)
        if not spec or not operation or step.card.id != spec.id:
            fail("Карточка отсутствует в снимке раунда.", index, "card")
        spec = spec.with_overrides(operation.overrides)
        if step.card.code == "purchase":
            from src.aml_workshop_simulator.domain.catalog import catalog_entry

            if behavior.purchases is None or step.card.version != 1:
                fail("Покупки не включены в снимке раунда.", index, "card")
            fixed = catalog_entry("purchase")
            for name in (
                "min_amount",
                "max_amount",
                "max_occurrences",
                "energy_cost",
                "time_cost",
                "fee_rate",
                "flow",
                "channels",
                "risk_weight",
            ):
                if getattr(spec, name) != fixed[name]:
                    fail(
                        "Параметры покупки не соответствуют purchase-policy-v1.",
                        index,
                        "card",
                    )

        if not spec.min_amount <= step.amount <= spec.max_amount:
            fail("Сумма вне лимитов карточки.", index, "amount")
        if step.card.code not in PARTY_ROLES:
            fail("Для карточки не определены роли сторон.", index, "card")
        role, kinds = PARTY_ROLES[step.card.code]
        for field in ("sender_id", "recipient_id"):
            identity = getattr(step, field)
            if field != role:
                if identity is not None:
                    fail("Для операции эта сторона неприменима.", index, field)
            elif identity not in parties:
                fail("Выберите сторону из каталога этого раунда.", index, field)
            elif not party_allowed(
                step.card.code, parties[identity], behavior.sender_policy
            ):
                fail("Тип стороны не подходит для операции.", index, field)
        declarations = {
            f["key"]: f for f in spec.fields if f["key"] != "sender_relationship"
        }
        if step.action_details.keys() - declarations.keys():
            fail(
                "Неизвестные или производные характеристики операции.",
                index,
                "action_details",
            )
        details = {}
        for name, declaration in declarations.items():
            value = step.action_details.get(name, declaration["default"])
            if value not in [
                option["value"] for option in declaration.get("options", [])
            ]:
                fail(
                    "Недопустимое значение параметра.", index, f"action_details.{name}"
                )
            details[name] = value
        channel = step.context.channel
        if channel is None and spec.channels:
            channel = spec.channels[0]
        if channel is not None and channel not in spec.channels:
            fail("Канал не подходит для карточки.", index, "context.channel")
        output = step.model_dump(mode="json")
        output["context"] = {"channel": str(channel)} if channel is not None else {}
        output["action_details"] = details
        output["interval_minutes"] = (
            None if index == 1 else (step.interval_minutes or 1)
        )
        result.append(output)
    return result


def resolve_counterparty_links(steps, config):
    """Observable links, recomputed in chain order; no risk contribution implied."""
    canonical = canonical_expanded_steps(steps, config)
    behavior = behavior_for(config)
    parties = {party.id: party for party in behavior.counterparties}
    history = behavior.history.operations
    historical_in = Counter(
        op.counterparty_id
        for op in history or []
        if op.operation_code in {"salary", "incoming_transfer"}
    )
    historical_out = Counter(
        op.counterparty_id
        for op in history or []
        if op.operation_code in {"card_transfer", "purchase"}
    )
    incoming, outgoing = Counter(), Counter()
    result = []
    for step in canonical:
        row = {"step_id": step["step_id"], "sender": None, "recipient": None}
        for role in ("sender", "recipient"):
            identity = step[role + "_id"]
            if identity is None:
                continue
            row[role] = {
                **parties[identity].model_dump(mode="json"),
                "history_available": history is not None,
                "historical_incoming_count": historical_in[identity]
                if history is not None
                else None,
                "historical_outgoing_count": historical_out[identity]
                if history is not None
                else None,
                "prior_incoming_count": incoming[identity],
                "prior_outgoing_count": outgoing[identity],
                "return_to_observed_sender": role == "recipient"
                and (incoming[identity] > 0 or historical_in[identity] > 0),
            }
        if step["sender_id"]:
            incoming[step["sender_id"]] += 1
        if step["recipient_id"]:
            outgoing[step["recipient_id"]] += 1
        result.append(row)
    return result
