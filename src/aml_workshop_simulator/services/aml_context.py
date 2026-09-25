"""V10 evidence resolution and lossless projection onto frozen v9 resources.

Evidence is scoped transaction context, never a risk label or money provenance trace.
No model or historical scoring rubric is invoked here.
"""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from pydantic import model_validator

from src.aml_workshop_simulator.domain.operation_timeline import operation_timeline
from src.aml_workshop_simulator.schemas.aml_context import AMLContext
from src.aml_workshop_simulator.schemas.scenarios import AMLScenarioStepIn
from src.aml_workshop_simulator.services import semantic_contract


class BehaviorV10(semantic_contract.BehaviorV9):
    aml_context: AMLContext

    @model_validator(mode="after")
    def versioned_history_required(self):
        if self.history.version is None:
            raise ValueError("V10 requires versioned observed history")
        return self


def validate_context(context: dict, config: dict) -> None:
    parsed = AMLContext.model_validate(context)
    parties = {p["id"] for p in config["behavior"]["counterparties"]}
    operations = {op["code"] for op in config["operations"]}
    for fact in parsed.facts:
        if set(fact.counterparty_ids) - parties:
            raise ValueError("Evidence references an unknown counterparty")
        if set(fact.operation_codes) - operations:
            raise ValueError("Evidence references an unknown operation")
    start = datetime.fromisoformat(config["behavior"]["timeline"]["starts_at"])
    if parsed.as_of < start:
        raise ValueError("Context as_of cannot precede the scenario and its history")
    history = config["behavior"]["history"]
    if parsed.history_coverage == "unknown" and history["operations"] is not None:
        raise ValueError("Unknown coverage requires unavailable history; use partial for observed fragments")
    if parsed.history_coverage != "unknown":
        if history["operations"] is None:
            raise ValueError("Known coverage requires observed history (empty is allowed)")
        if parsed.history_end > start:
            raise ValueError("History coverage cannot extend into the scenario")
        for event in history["operations"]:
            if not parsed.history_start <= datetime.fromisoformat(event["occurred_at"]) < parsed.history_end:
                raise ValueError("History event falls outside declared coverage")
        if parsed.history_coverage == "complete" and (
            parsed.history_start != start - timedelta(days=history["window_days"])
            or parsed.history_end != start
        ):
            raise ValueError("Complete history must cover the configured history window")


def validate_config(config: dict) -> None:
    if config.get("schema_version") != 10:
        raise ValueError("Expected v10 AML context contract")
    BehaviorV10.model_validate(config["behavior"])
    validate_context(config["behavior"]["aml_context"], config)


def semantic_config(config: dict) -> dict:
    """Private observation projection, never an old-model scoring fallback."""
    validate_config(config)
    result = deepcopy(config)
    result["schema_version"] = 9
    result["behavior"].pop("aml_context")
    return result


def semantic_steps(steps: list) -> list:
    result = []
    for raw in steps:
        step = raw.model_dump(mode="json") if hasattr(raw, "model_dump") else deepcopy(raw)
        step.pop("purpose_code", None)
        step.pop("claim_id", None)
        result.append(step)
    return result


def canonical_steps(steps: list, config: dict) -> list:
    validate_config(config)
    context = AMLContext.model_validate(config["behavior"]["aml_context"])
    purposes = {p.code for p in context.purpose_catalog}
    facts = {f.id: f for f in context.facts}
    parsed = [AMLScenarioStepIn.model_validate(
        raw.model_dump(mode="json") if hasattr(raw, "model_dump") else raw
    ) for raw in steps]
    for step in parsed:
        if step.purpose_code not in purposes:
            raise ValueError("Step purpose is outside the round catalog")
        from src.aml_workshop_simulator.domain.operation_purposes import validate_purpose

        validate_purpose(step.model_dump(mode="json"))
        if step.claim_id is not None:
            if step.claim_id not in facts:
                raise ValueError("Unknown claim reference")
            if facts[step.claim_id].fact_type == "opening_balance":
                raise ValueError("An opening balance fact cannot be a transaction claim")
    canonical = semantic_contract.canonical_steps(semantic_steps(parsed), semantic_config(config))
    for step, origin in zip(canonical, parsed):
        step["purpose_code"] = origin.purpose_code
        step["claim_id"] = origin.claim_id
    return canonical


def resolve_evidence(steps: list, config: dict) -> list[dict]:
    canonical = canonical_steps(steps, config)
    context = AMLContext.model_validate(config["behavior"]["aml_context"])
    timeline = operation_timeline(canonical, config["behavior"]["timeline"])
    if not timeline:
        return []
    cutoff = min(context.as_of, datetime.fromisoformat(timeline[-1]["occurred_at"]))
    facts = {f.id: f for f in context.facts}
    remaining = {f.id: {"credit": f.max_credit_amount, "debit": f.max_debit_amount} for f in context.facts}
    rows = []
    for step, moment in zip(canonical, timeline):
        code = step["card"]["code"]
        direction = "credit" if code in {"salary", "incoming_transfer"} else "debit"
        party = step.get("sender_id") or step.get("recipient_id")
        occurred = datetime.fromisoformat(moment["occurred_at"])
        fact = facts.get(step["claim_id"])
        available = fact is not None and fact.available_at <= cutoff
        scope_matches = available and (
            code in fact.operation_codes
            and fact.purpose_code == step["purpose_code"]
            and fact.valid_from <= occurred <= fact.valid_to
            and (party in fact.counterparty_ids if party is not None else not fact.counterparty_ids)
        )
        status = fact.verification_status if available else "unknown"
        covered = Decimal(0)
        # A verified relationship does not establish the legitimacy of any amount.
        amount_fact = fact is not None and fact.fact_type in {"source_of_funds", "payment_purpose"}
        if scope_matches and status == "verified" and amount_fact:
            covered = min(Decimal(step["amount"]), remaining[fact.id][direction])
            remaining[fact.id][direction] -= covered
        rows.append({
            "step_id": step["step_id"], "applicable": bool(scope_matches),
            "verification_status": status,
            "mismatch": bool(available and not scope_matches),
            "contradicted": bool(scope_matches and status == "contradicted"),
            "unknown": not available or status == "unknown",
            "covered_credit_amount": f"{covered if direction == 'credit' else Decimal(0):.2f}",
            "covered_debit_amount": f"{covered if direction == 'debit' else Decimal(0):.2f}",
            "fact_ids": [fact.id] if scope_matches else [],
        })
    return rows


def evaluate(steps: list, config: dict) -> dict:
    canonical = canonical_steps(steps, config)
    return _evaluate_canonical(canonical, config)


def _evaluate_canonical(canonical, config, specs=None, policy=None):
    return semantic_contract._evaluate_canonical(semantic_steps(canonical), semantic_config(config), specs, policy)
