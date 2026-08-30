"""Atomic batch scoring of one round.

The whole batch runs inside a single transaction: either every submitted
scenario receives a result and the round becomes `completed`, or nothing is
published and the round stays `active`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aml_workshop_simulator.db.models.audit_events import AuditEvent
from aml_workshop_simulator.db.models.rounds import Round
from aml_workshop_simulator.db.models.scenarios import Scenario
from aml_workshop_simulator.db.models.scoring_results import ScoringResult
from aml_workshop_simulator.domain.scoring import (
    LEADERBOARD_VERSION,
    SCORING_VERSION,
    leaderboard_scores,
    resource_score,
    score_scenario,
)
from aml_workshop_simulator.services.scenario_service import (
    build_snapshot,
    load_round_card_specs,
    round_policy,
)
from aml_workshop_simulator.services.scenario_versions import submitted_steps

#: Test hook: called with the 1-based index of each scenario before it is
#: written, so atomicity can be verified with a controlled failure.
SCORING_FAILURE_HOOK: Callable[[int, Scenario], None] | None = None


class NoSubmissions(Exception):
    pass


async def score_round(
    db: AsyncSession,
    round_obj: Round,
    actor_user_id: int,
    request_id: str | None = None,
    idempotency_key_hash: str | None = None,
) -> dict[str, Any]:
    """Score every submitted scenario of `round_obj` in one transaction."""
    started = time.perf_counter()

    scenarios = (
        (
            await db.execute(
                select(Scenario)
                .where(Scenario.round_id == round_obj.id, Scenario.status == "submitted")
                .order_by(Scenario.id)
            )
        )
        .scalars()
        .all()
    )
    if not scenarios:
        raise NoSubmissions()

    draft_count = (
        await db.execute(
            select(func.count(Scenario.id)).where(
                Scenario.round_id == round_obj.id, Scenario.status == "draft"
            )
        )
    ).scalar() or 0

    specs = await load_round_card_specs(db, round_obj)
    policy = round_policy(round_obj, specs)
    game_config = round_obj.game_config or {}
    now = datetime.now(UTC)
    scored = 0

    for index, scenario in enumerate(scenarios, start=1):
        if SCORING_FAILURE_HOOK is not None:
            SCORING_FAILURE_HOOK(index, scenario)

        # Only the version the participant actually submitted is scored, even
        # if a later draft exists in the history.
        steps = await submitted_steps(db, scenario)
        snapshot = build_snapshot(steps, specs, game_config, policy)
        scoring = score_scenario(steps, specs, game_config)
        risk: Decimal = scoring["risk_score"]
        resources = resource_score(snapshot, game_config)
        board = leaderboard_scores(risk, resources, game_config)

        existing = (
            await db.execute(
                select(ScoringResult).where(ScoringResult.scenario_id == scenario.id)
            )
        ).scalars().first()
        if existing is None:
            db.add(
                ScoringResult(
                    scenario_id=scenario.id,
                    risk_score=risk,
                    risk_label=scoring["risk_label"].value,
                    stealth_score=board["stealth_score"],
                    resource_score=board["resource_score"],
                    game_score=board["game_score"],
                    explanation=scoring["explanation"],
                    scoring_version=SCORING_VERSION,
                    leaderboard_version=LEADERBOARD_VERSION,
                    created_at=now,
                )
            )
        else:
            existing.risk_score = risk
            existing.risk_label = scoring["risk_label"].value
            existing.stealth_score = board["stealth_score"]
            existing.resource_score = board["resource_score"]
            existing.game_score = board["game_score"]
            existing.explanation = scoring["explanation"]

        scenario.resource_snapshot = snapshot
        scenario.status = "scored"
        scored += 1

    duration_ms = int((time.perf_counter() - started) * 1000)
    summary = {
        "submitted_count": len(scenarios),
        "scored_count": scored,
        "excluded_draft_count": int(draft_count),
        "duration_ms": duration_ms,
        "scoring_version": SCORING_VERSION,
        "leaderboard_version": LEADERBOARD_VERSION,
        "completed_at": now.isoformat(),
    }
    round_obj.status = "completed"
    round_obj.completed_at = now
    round_obj.scoring_summary = summary

    db.add(
        AuditEvent(
            actor_user_id=actor_user_id,
            round_id=round_obj.id,
            event_type="round_scored",
            target_type="round",
            target_id=str(round_obj.id),
            reason=f"Scored {scored} submitted scenarios",
            request_id=request_id,
            idempotency_key_hash=idempotency_key_hash,
            metadata_={
                "submitted_count": len(scenarios),
                "scored_count": scored,
                "excluded_draft_count": int(draft_count),
            },
            created_at=now,
        )
    )
    return summary
