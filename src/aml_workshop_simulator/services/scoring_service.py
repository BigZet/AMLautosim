"""Atomic scoring of the submitted scenarios in the current round."""

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.db.models.scoring_results import ScoringResult
from src.aml_workshop_simulator.domain.contract_versions import (
    require_playable_contract,
)
from src.aml_workshop_simulator.domain.scoring import (
    LEADERBOARD_VERSION,
    AML_LEADERBOARD_VERSION,
    probability_leaderboard_scores,
    leaderboard_scores,
    resource_score,
)
from src.aml_workshop_simulator.services.audit import record_event
from src.aml_workshop_simulator.services.scenario_service import (
    build_snapshot,
    load_round_card_specs,
    round_policy,
)


async def score_round(
    db: AsyncSession,
    round_obj: Round,
    actor_user_id: int,
    request_id: str | None = None,
    *,
    prepared: list[dict] | None = None,
    duration_ms: int | None = None,
) -> dict:
    """Caller holds an exclusive round lock and commits the whole batch once.

    Admission is already closed. The caller discards partial results on failure.
    An empty game also completes.
    """
    require_playable_contract(round_obj.game_config)
    started = time.perf_counter()
    scenarios = (
        (
            await db.execute(
                select(Scenario)
                .where(
                    Scenario.round_id == round_obj.id, Scenario.status == "submitted"
                )
                .order_by(Scenario.id)
            )
        )
        .scalars()
        .all()
    )
    specs = load_round_card_specs(round_obj)
    policy = round_policy(round_obj, specs)
    now = datetime.now(UTC)
    from src.aml_workshop_simulator.services.model_scoring import get_round_scorer

    scorer = get_round_scorer(round_obj.game_config)
    scorer.check_config(round_obj.game_config, require_pin=True)
    scoring_version = scorer.identity["model_version"]
    leaderboard_version = (
        AML_LEADERBOARD_VERSION
        if round_obj.game_config["schema_version"] == 10
        else LEADERBOARD_VERSION
    )
    calculated = (
        {item["id"]: item for item in prepared} if prepared is not None else None
    )
    if calculated is not None and set(calculated) != {s.id for s in scenarios}:
        raise ValueError("prepared_scenarios_mismatch")
    for scenario in scenarios:
        # CPU work receives plain data; the database session stays on this loop.
        if calculated is None:
            snapshot, values = await asyncio.to_thread(
                _evaluate, scenario.steps, specs, round_obj.game_config, policy, scorer
            )
        else:
            snapshot, values = (
                calculated[scenario.id]["snapshot"],
                calculated[scenario.id]["values"],
            )
        db.add(
            ScoringResult(
                scenario_id=scenario.id,
                **values,
                scoring_version=scoring_version,
                leaderboard_version=leaderboard_version,
                created_at=now,
            )
        )
        scenario.resource_snapshot = snapshot
        scenario.status = "scored"
    summary = dict(
        submitted_count=len(scenarios),
        scored_count=len(scenarios),
        duration_ms=duration_ms
        if duration_ms is not None
        else int((time.perf_counter() - started) * 1000),
        scoring_version=scoring_version,
        leaderboard_version=leaderboard_version,
    )
    round_obj.status = "completed"
    round_obj.completed_at = now
    round_obj.scoring_summary = summary
    await record_event(
        db,
        actor_user_id=actor_user_id,
        round_id=round_obj.id,
        event_type="round_scored",
        request_id=request_id,
        metadata=summary,
    )
    return summary


def _evaluate(
    steps, specs, config, policy, scorer=None
) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = build_snapshot(steps, specs, config, policy)
    from src.aml_workshop_simulator.services.model_scoring import get_round_scorer

    scoring = (scorer or get_round_scorer(config)).score(steps, config)
    resources = resource_score(snapshot, config)
    board = (
        probability_leaderboard_scores(
            scoring["explanation"]["aml_probability"], resources, config
        )
        if config["schema_version"] == 10
        else leaderboard_scores(scoring["risk_score"], resources, config)
    )
    return snapshot, {
        **board,
        "risk_score": scoring["risk_score"],
        "risk_label": scoring["risk_label"],
        "explanation": scoring["explanation"],
    }
