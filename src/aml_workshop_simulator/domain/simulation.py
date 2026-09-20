"""Simulation for the scenario engine."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any

from src.aml_workshop_simulator.domain.contract_versions import (
    require_legacy_contract,
)
from src.aml_workshop_simulator.domain.round_policy import (
    RoundPolicy,
)

from .game_models import (
    QUOTA_LABELS,
    RULESET_VERSION,
    SNAPSHOT_SCHEMA_VERSION,
    ZERO,
    CardSpec,
    RoundRules,
    StructuralError,
    Violation,
    _fmt_money,
    _step_label,
    money,
)
from .structure import resolve_policy, validate_structure


def action_detail_effects(spec: CardSpec, details: dict[str, Any]) -> dict[str, Any]:
    """Resource and risk effects of the selected action details."""
    result: dict[str, Any] = {
        "risk_points": ZERO,
        "time_cost": 0,
        "energy_cost": 0,
        "factors": [],
    }
    for field_spec in spec.fields:
        key = field_spec["key"]
        if key not in details:
            continue
        value = details[key]
        option = next(
            (item for item in field_spec.get("options", []) if item["value"] == value),
            None,
        )
        if option is None:
            continue
        points = Decimal(str(option.get("risk_points", 0)))
        result["factors"].append(
            {
                "field_key": key,
                "field_label": field_spec["label"],
                "value": value,
                "value_label": option["label"],
                "risk_points": points,
                "description": option.get("description", ""),
            }
        )
        result["risk_points"] += points
        result["time_cost"] += int(option.get("time_cost", 0))
        result["energy_cost"] += int(option.get("energy_cost", 0))
    return result


def _check_operation(
    spec: CardSpec,
    amount: Decimal,
    index: int,
    step_id: str,
    card_counts: dict[str, int],
) -> list[Violation]:
    """Check the amount, prerequisites and number of cards used in this round."""
    violations: list[Violation] = []
    # ---- per-step limits ------------------------------------------------
    if amount < spec.min_amount or amount > spec.max_amount:
        violations.append(
            Violation(
                reason="amount_out_of_range",
                step_id=step_id,
                step_index=index,
                field="amount",
                current=str(amount),
                allowed=f"{spec.min_amount}..{spec.max_amount}",
                message=(
                    f"{_step_label(index, spec)}, поле «Сумма»: указано "
                    f"{_fmt_money(amount)}, допустимо от {_fmt_money(spec.min_amount)} "
                    f"до {_fmt_money(spec.max_amount)} за одну операцию. "
                    "Измените сумму в допустимый диапазон."
                ),
            )
        )
    if spec.requires_card_code and not card_counts.get(spec.requires_card_code):
        violations.append(
            Violation(
                reason="required_operation_missing",
                step_id=step_id,
                step_index=index,
                field="card",
                allowed=spec.requires_card_code,
                message=f"{_step_label(index, spec)}: сначала выполните операцию «{spec.requires_card_code}».",
            )
        )

    card_counts[spec.code] = card_counts.get(spec.code, 0) + 1
    if card_counts[spec.code] > spec.max_occurrences:
        violations.append(
            Violation(
                reason="max_occurrences_exceeded",
                step_id=step_id,
                step_index=index,
                field="card",
                current=str(card_counts[spec.code]),
                allowed=str(spec.max_occurrences),
                message=(
                    f"{_step_label(index, spec)}: суммарно по карточке «{spec.title}» "
                    f"набрано {card_counts[spec.code]} карточек за раунд, лимит — "
                    f"{spec.max_occurrences}. Удалите лишние "
                    "карточки этой операции."
                ),
            )
        )

    return violations


def _resource_costs(
    spec: CardSpec,
    context: dict[str, Any],
    gross: Decimal,
    effects: dict[str, Any],
    costs: dict[str, Any],
    *,
    waiting_time_cost: int | None = None,
) -> tuple[int, int]:
    """Energy and time charged once for this transaction."""
    energy_cost = spec.energy_cost + effects["energy_cost"]
    declared = {f["key"] for f in spec.context_fields}
    velocity_time = (
        costs["velocity_time"][context["velocity"]]["time_cost"]
        if waiting_time_cost is None and "velocity" in declared
        else 0
    )
    adjustment = costs["amount_adjustment"]
    amount_time = (
        adjustment["time_cost"]
        if gross >= Decimal(str(adjustment["minimum_gross"]))
        else 0
    )
    channel_time = costs["channel_time"][context["channel"]] if spec.channels else 0
    time_cost = max(
        costs["minimum_time_cost"],
        spec.time_cost
        + velocity_time
        + amount_time
        + channel_time
        + effects["time_cost"],
    )
    return energy_cost, time_cost + (waiting_time_cost or 0)


def _limit_report(
    rules: RoundRules,
    quotas: dict[str, Decimal],
    nights: int,
    anonymous: int,
    actions: int,
) -> list[dict[str, Any]]:
    entries = [
        (key, QUOTA_LABELS[key], "money", quotas[key], limit)
        for key, limit in rules.category_limits.items()
    ]
    entries.extend(
        [
            ("actions", "Действия в раунде", "count", actions, rules.max_actions),
        ]
    )
    return [
        {
            "code": code,
            "label": label,
            "kind": kind,
            "used": str(used),
            "limit": str(limit),
            "remaining": str(max(0, limit - used)),
        }
        for code, label, kind, used, limit in entries
    ]


def evaluate_scenario(
    steps: Sequence[dict[str, Any]],
    card_specs: dict[tuple[str, int], CardSpec],
    game_config: dict[str, Any] | None,
    policy: RoundPolicy | None = None,
) -> dict[str, Any]:
    """Compute the canonical resource snapshot for a structurally valid chain.

    Raises `StructuralError` when the payload breaks a card version contract.
    """
    require_legacy_contract(game_config)
    policy = resolve_policy(card_specs, game_config, policy)
    structural = validate_structure(steps, card_specs, policy)
    if structural:
        raise StructuralError(structural)

    return _evaluate_validated(steps, card_specs, game_config, policy)


def _evaluate_validated(
    steps, card_specs, game_config, policy, *, timeline=None, purchase_policy=None
):
    """Shared accounting kernel; callers must validate their version's input."""
    rules = RoundRules.from_config(game_config)
    costs = game_config["resource_rules"]
    violations: list[Violation] = []

    balance = rules.initial_balance
    energy = rules.initial_energy
    time_left = rules.initial_time
    inflow = ZERO
    outflow = ZERO
    target_outflow = ZERO
    purchase_outflow = ZERO
    purchase_limit_reported = False
    fees = ZERO
    night_operations = 0
    anonymous_operations = 0
    previous_code: str | None = None
    identical_streak = 0
    card_counts: dict[str, int] = {}
    quota_usage: dict[str, Decimal] = {key: ZERO for key in QUOTA_LABELS}
    quota_reported: set[str] = set()
    per_step: list[dict[str, Any]] = []

    if len(steps) > rules.max_actions:
        violations.append(
            Violation(
                reason="max_actions_exceeded",
                field="steps",
                current=str(len(steps)),
                allowed=str(rules.max_actions),
                message=(
                    f"В цепочке {len(steps)} шагов, а раунд допускает не более "
                    f"{rules.max_actions}. Удалите лишние шаги."
                ),
            )
        )

    for index, step in enumerate(steps, start=1):
        step_id = str(step["step_id"])
        card_key = (step["card"]["code"], int(step["card"]["version"]))
        operation = policy.for_card(card_key)
        spec = card_specs[card_key].with_overrides(
            operation.overrides if operation else None
        )
        resources_before = {
            "balance": str(balance),
            "energy": energy,
            "time": time_left,
        }
        amount = money(step["amount"])
        context = step["context"]
        recipient_type = context.get("recipient_type")
        timing = timeline[index - 1] if timeline is not None else None
        time_of_day = timing["time_of_day"] if timing else context.get("time_of_day")
        details = dict(step.get("action_details") or {})
        effects = action_detail_effects(spec, details)

        gross = amount
        fee = money(gross * spec.fee_rate)

        violations.extend(_check_operation(spec, amount, index, step_id, card_counts))

        # ---- sequence rules -------------------------------------------------
        if previous_code == spec.code:
            identical_streak += 1
        else:
            identical_streak = 1
            previous_code = spec.code
        if identical_streak > rules.max_identical_steps:
            violations.append(
                Violation(
                    reason="identical_streak_exceeded",
                    step_id=step_id,
                    step_index=index,
                    field="card",
                    current=str(identical_streak),
                    allowed=str(rules.max_identical_steps),
                    message=(
                        f"{_step_label(index, spec)}: подряд идет {identical_streak} одинаковых "
                        f"операций, допустимо не более {rules.max_identical_steps}. "
                        "Переставьте шаги так, чтобы между ними была другая операция."
                    ),
                )
            )

        if time_of_day == "night":
            night_operations += 1

        if recipient_type == "anonymous_wallet":
            anonymous_operations += 1

        energy_cost, time_cost = _resource_costs(
            spec,
            context,
            gross,
            effects,
            costs,
            waiting_time_cost=timing["waiting_time_cost"] if timing else None,
        )
        # ---- money ----------------------------------------------------------
        if spec.flow == "credit":
            money_delta = money(gross - fee)
            inflow = money(inflow + gross)
        elif spec.flow == "debit":
            money_delta = money(-(gross + fee))
            outflow = money(outflow + gross)
            if spec.code in {"card_transfer", "cash_withdrawal"}:
                target_outflow = money(target_outflow + gross)
            if purchase_policy is not None and spec.code == "purchase":
                purchase_outflow = money(purchase_outflow + gross)
                if (
                    purchase_outflow > money(purchase_policy["max_total"])
                    and not purchase_limit_reported
                ):
                    purchase_limit_reported = True
                    violations.append(
                        Violation(
                            reason="purchase_total_exceeded",
                            step_id=step_id,
                            step_index=index,
                            field="amount",
                            current=str(purchase_outflow),
                            allowed=str(money(purchase_policy["max_total"])),
                            message=f"Общая сумма покупок превышает {_fmt_money(money(purchase_policy['max_total']))} ₽. Уменьшите сумму или удалите покупку.",
                        )
                    )
        else:  # neutral
            money_delta = money(-fee)

        # ---- quotas ---------------------------------------------------------
        if spec.quota_category:
            quota_usage[spec.quota_category] = money(
                quota_usage[spec.quota_category] + gross
            )
        if recipient_type == "anonymous_wallet":
            quota_usage["anonymous"] = money(quota_usage["anonymous"] + gross)
        for quota_code, limit in rules.category_limits.items():
            if quota_code not in quota_usage:
                continue
            if quota_usage[quota_code] > limit and quota_code not in quota_reported:
                quota_reported.add(quota_code)
                violations.append(
                    Violation(
                        reason="category_limit_exceeded",
                        step_id=step_id,
                        step_index=index,
                        field="amount",
                        current=str(quota_usage[quota_code]),
                        allowed=str(limit),
                        message=(
                            f"{_step_label(index, spec)}: квота «{QUOTA_LABELS[quota_code]}» "
                            f"использована на {_fmt_money(quota_usage[quota_code])} при лимите "
                            f"{_fmt_money(limit)} за раунд. Уменьшите сумму или замените "
                            "операцию другой категорией."
                        ),
                    )
                )

        balance = money(balance + money_delta)
        fees = money(fees + fee)
        energy -= energy_cost
        time_left -= time_cost

        if balance < ZERO:
            violations.append(
                Violation(
                    reason="insufficient_balance",
                    step_id=step_id,
                    step_index=index,
                    field="amount",
                    current=str(balance),
                    allowed="0.00",
                    message=(
                        f"{_step_label(index, spec)}, поле «Сумма»: после операции и комиссии "
                        f"баланс становится {_fmt_money(balance)} — денег не хватает. "
                        "Уменьшите сумму или добавьте поступление раньше по цепочке."
                    ),
                )
            )
        if energy < 0:
            violations.append(
                Violation(
                    reason="insufficient_energy",
                    step_id=step_id,
                    step_index=index,
                    field="card",
                    current=str(energy),
                    allowed="0",
                    message=(
                        f"{_step_label(index, spec)}: не хватает энергии (остаток {energy}). "
                        "Удалите один из шагов или выберите менее затратную операцию."
                    ),
                )
            )
        if time_left < 0:
            violations.append(
                Violation(
                    reason="insufficient_time",
                    step_id=step_id,
                    step_index=index,
                    field="card",
                    current=str(time_left),
                    allowed="0",
                    message=(
                        f"{_step_label(index, spec)}: не хватает времени раунда "
                        f"(остаток {time_left}). Уберите шаг, ускорьте темп или откажитесь "
                        "от обслуживания в отделении."
                    ),
                )
            )
        per_step.append(
            {
                "step_id": step_id,
                "step_index": index,
                "card_code": spec.code,
                "card_version": spec.version,
                "card_title": spec.title,
                "resources_before": resources_before,
                "resources_after": {
                    "balance": str(balance),
                    "energy": energy,
                    "time": time_left,
                },
                "gross": str(gross),
                "fee": str(fee),
                "money_delta": str(money_delta),
                "energy_cost": energy_cost,
                "time_cost": time_cost,
                "detail_factors": [
                    {**factor, "risk_points": str(factor["risk_points"])}
                    for factor in effects["factors"]
                ],
            }
        )

        if purchase_policy is not None and spec.code == "purchase":
            party = next(
                p
                for p in game_config["behavior"]["counterparties"]
                if p["id"] == step["recipient_id"]
            )
            per_step[-1]["purchase"] = {
                "merchant_id": party["id"],
                "category": party.get("category"),
            }

    available_steps = max(0, rules.max_actions - len(steps))
    goal_reached = (
        target_outflow if purchase_policy is not None else outflow
    ) >= rules.target_outflow

    snapshot: dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "ruleset_version": RULESET_VERSION,
        "valid": not violations,
        "resources_after": {
            "balance": str(balance),
            "energy": energy,
            "time": time_left,
            "available_steps": available_steps,
        },
        "totals": {
            "gross_inflow": str(inflow),
            "gross_outflow": str(outflow),
            "fees": str(fees),
        },
        "objective": {
            "target_outflow": str(rules.target_outflow),
            "reached": goal_reached,
        },
        "limit_usage": {
            **{key: str(value) for key, value in quota_usage.items()},
            "night_operations": night_operations,
            "anonymous_operations": anonymous_operations,
            "actions": len(steps),
        },
        "limits": _limit_report(
            rules, quota_usage, night_operations, anonymous_operations, len(steps)
        ),
        "violations": [violation.as_dict() for violation in violations],
        "per_step": per_step,
    }
    if timeline is not None:
        snapshot["schema_version"] = 6
        snapshot["ruleset_version"] = "expanded-rules-stage03-v1"
        snapshot["timeline"] = {
            "version": "operation-timeline-v1",
            "timezone": game_config["behavior"]["timeline"]["timezone"],
            "steps": [
                {
                    **item,
                    "operation_time_cost": impact["time_cost"]
                    - item["waiting_time_cost"],
                }
                for item, impact in zip(timeline, per_step)
            ],
        }
    if purchase_policy is not None:
        snapshot["schema_version"] = 7
        snapshot["ruleset_version"] = "expanded-rules-stage04-v1"
        snapshot["totals"].update(
            target_outflow=str(target_outflow), purchase_outflow=str(purchase_outflow)
        )
        for code, label, kind, used, limit in [
            (
                "purchase_total",
                "Сумма покупок",
                "money",
                purchase_outflow,
                money(purchase_policy["max_total"]),
            ),
            (
                "purchase_count",
                "Количество покупок",
                "count",
                card_counts.get("purchase", 0),
                3,
            ),
        ]:
            snapshot["limits"].append(
                {
                    "code": code,
                    "label": label,
                    "kind": kind,
                    "used": str(used),
                    "limit": str(limit),
                    "remaining": str(max(0, limit - used)),
                }
            )
    return snapshot


def submit_blockers(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Reasons a structurally valid chain still may not be submitted."""
    blockers = list(snapshot.get("violations", []))
    if not snapshot.get("per_step"):
        blockers.append(
            Violation(
                reason="scenario_empty",
                field="steps",
                current="0",
                allowed="1..",
                message=(
                    "Цепочка пуста. Добавьте хотя бы одну операцию, чтобы отправить сценарий."
                ),
            ).as_dict()
        )
    objective = snapshot.get("objective", {})
    if not objective.get("reached", False):
        target = money(objective.get("target_outflow", "0"))
        current = money(
            snapshot.get("totals", {}).get(
                "target_outflow", snapshot.get("totals", {}).get("gross_outflow", "0")
            )
        )
        blockers.append(
            Violation(
                reason="target_outflow_not_reached",
                field="objective.target_outflow",
                current=str(current),
                allowed=str(target),
                message=(
                    f"Цель раунда не достигнута: расходный оборот {_fmt_money(current)} "
                    f"из необходимых {_fmt_money(target)}. Добавьте или увеличьте расходные "
                    "операции."
                ),
            ).as_dict()
        )
    return blockers


def specs_by_key(specs: Iterable[CardSpec]) -> dict[tuple[str, int], CardSpec]:
    return {spec.key: spec for spec in specs}
