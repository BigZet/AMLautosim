"""Shared v8 evaluation; snapshot availability and creation are checked separately."""

from src.aml_workshop_simulator.domain.operation_timeline import operation_timeline
from src.aml_workshop_simulator.domain.round_policy import RoundPolicy
from src.aml_workshop_simulator.domain.simulation import _evaluate_validated
from src.aml_workshop_simulator.services.configuration import snapshot_specs
from src.aml_workshop_simulator.services.counterparties import (
    canonical_expanded_steps,
)


def evaluate_expanded_scenario(steps, config):
    if config.get("schema_version") == 10:
        from src.aml_workshop_simulator.services.aml_context import evaluate
        return evaluate(steps, config)
    if config.get("schema_version") == 9:
        from src.aml_workshop_simulator.services.semantic_contract import evaluate
        return evaluate(steps, config)
    canonical = canonical_expanded_steps(steps, config)
    return _evaluate_canonical(canonical, config)


def _evaluate_canonical(canonical, config, specs=None, policy=None):
    """Private kernel dispatch; public entry points still canonicalize raw input."""
    if config.get('schema_version') == 10:
        from src.aml_workshop_simulator.services.aml_context import _evaluate_canonical as evaluate
        return evaluate(canonical, config, specs, policy)
    if config.get('schema_version') == 9:
        from src.aml_workshop_simulator.services.semantic_contract import _evaluate_canonical as evaluate
        return evaluate(canonical, config, specs, policy)
    specs = snapshot_specs(config) if specs is None else specs
    timeline = operation_timeline(canonical, config["behavior"]["timeline"])
    purchase_policy = config['behavior'].get('purchases')
    if purchase_policy is not None:
        from src.aml_workshop_simulator.schemas.expanded_contract import PurchasePolicy
        purchase_policy = PurchasePolicy.model_validate(purchase_policy).model_dump(mode="json")
    return _evaluate_validated(
        canonical,
        specs,
        config,
        policy or RoundPolicy.from_config(config, specs),
        timeline=timeline,
        purchase_policy=purchase_policy,
    )


def score_expanded_scenario(steps, config):
    """Temporary deterministic comparator; not a reviewed dataset rubric."""
    if config.get("schema_version") == 10:
        raise ValueError("The v10 contract requires its pinned AML classifier")
    from src.aml_workshop_simulator.domain.scoring import _score_validated

    canonical = canonical_expanded_steps(steps, config)
    timeline = operation_timeline(canonical, config["behavior"]["timeline"])
    purchases_enabled = config["behavior"].get("purchases") is not None
    if purchases_enabled:
        # No average dilution or sequence interruption just by inserting a purchase.
        # Preserve elapsed time between the remaining financial operations.
        pairs = [
            (step, row)
            for step, row in zip(canonical, timeline)
            if step["card"]["code"] != "purchase"
        ]
        filtered, timed = [], []
        previous = None
        for step, row in pairs:
            interval = None if previous is None else row["elapsed_minutes"] - previous
            previous = row["elapsed_minutes"]
            filtered.append({**step, "interval_minutes": interval})
            timed.append(
                {
                    **row,
                    "pace": None
                    if interval is None
                    else "rapid"
                    if interval <= 1
                    else "normal"
                    if interval < 60
                    else "spaced",
                }
            )
        canonical, timeline = filtered, timed
    result = _score_validated(
        canonical, snapshot_specs(config), config, timeline=timeline
    )
    if purchases_enabled:
        result["explanation"]["scoring_version"] = "expanded-scoring-stage04-v1"
        result["explanation"]["purchase_policy"] = "excluded-from-risk-average-v1"
    return result
