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
from src.aml_workshop_simulator.domain.scoring import (
    LEADERBOARD_VERSION,
    SCORING_VERSION,
    leaderboard_scores,
    resource_score,
    score_scenario,
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
) -> dict:
    """Caller holds an exclusive round lock and commits the whole batch once.

    Admission is already closed. The caller discards partial results on failure.
    An empty game also completes.
    """
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
    for scenario in scenarios:
        # CPU work receives plain data; the database session stays on this loop.
        snapshot, values = await asyncio.to_thread(
            _evaluate, scenario.steps, specs, round_obj.game_config, policy
        )
        db.add(
            ScoringResult(
                scenario_id=scenario.id,
                **values,
                scoring_version=SCORING_VERSION,
                leaderboard_version=LEADERBOARD_VERSION,
                created_at=now,
            )
        )
        scenario.resource_snapshot = snapshot
        scenario.status = "scored"
    summary = dict(
        submitted_count=len(scenarios),
        scored_count=len(scenarios),
        duration_ms=int((time.perf_counter() - started) * 1000),
        scoring_version=SCORING_VERSION,
        leaderboard_version=LEADERBOARD_VERSION,
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


def _evaluate(steps, specs, config, policy) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = build_snapshot(steps, specs, config, policy)
    scoring = score_scenario(steps, specs, config)
    board = leaderboard_scores(
        scoring["risk_score"], resource_score(snapshot, config), config
    )
    return snapshot, {
        **board,
        "risk_score": scoring["risk_score"],
        "risk_label": scoring["risk_label"].value,
        "explanation": scoring["explanation"],
    }
