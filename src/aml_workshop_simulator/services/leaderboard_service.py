"""Leaderboard projection.

The base scoring result is immutable; an admin overlay only changes the
*effective* values. Ranking uses dense rank on the effective game score with
deterministic tie-breakers taken from the base result, so a manual override can
never hide the ordering rationale.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aml_workshop_simulator.db.models.leaderboard_adjustments import (
    LeaderboardAdjustment,
)
from aml_workshop_simulator.db.models.scenarios import Scenario
from aml_workshop_simulator.db.models.scoring_results import ScoringResult
from aml_workshop_simulator.db.models.users import User


def _effective(override: Any, base: Any) -> Decimal:
    return Decimal(str(override if override is not None else base))


async def _rows(db: AsyncSession, round_id: int) -> list[dict[str, Any]]:
    records = (
        await db.execute(
            select(Scenario, User, ScoringResult, LeaderboardAdjustment)
            .join(User, Scenario.participant_id == User.id)
            .join(ScoringResult, ScoringResult.scenario_id == Scenario.id)
            .outerjoin(
                LeaderboardAdjustment,
                LeaderboardAdjustment.scenario_id == Scenario.id,
            )
            .where(Scenario.round_id == round_id)
        )
    ).all()

    rows: list[dict[str, Any]] = []
    for scenario, user, result, adjustment in records:
        rows.append(
            {
                "scenario_id": int(scenario.id),
                "participant_id": int(user.id),
                "display_name": user.display_name or f"Участник #{user.id}",
                "email": user.email,
                "is_blocked": bool(user.is_blocked),
                "base_game_score": Decimal(str(result.game_score)),
                "base_risk_score": Decimal(str(result.risk_score)),
                "base_resource_score": Decimal(str(result.resource_score)),
                "stealth_score": Decimal(str(result.stealth_score)),
                "risk_label": result.risk_label,
                "effective_game_score": _effective(
                    adjustment.game_score_override if adjustment else None,
                    result.game_score,
                ),
                "effective_risk_score": _effective(
                    adjustment.risk_score_override if adjustment else None,
                    result.risk_score,
                ),
                "effective_resource_score": _effective(
                    adjustment.resource_score_override if adjustment else None,
                    result.resource_score,
                ),
                "is_adjusted": adjustment is not None,
                "adjustment_reason": adjustment.reason if adjustment else None,
            }
        )
    return rows


def _sort_and_rank(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows.sort(
        key=lambda row: (
            -row["effective_game_score"],
            row["base_risk_score"],
            -row["base_resource_score"],
            row["scenario_id"],
        )
    )
    rank = 0
    previous_key: tuple[Any, ...] | None = None
    for row in rows:
        key = (
            row["effective_game_score"],
            row["base_risk_score"],
            row["base_resource_score"],
        )
        if key != previous_key:
            rank += 1
            previous_key = key
        row["rank"] = rank
    return rows


async def build_public_leaderboard(
    db: AsyncSession, round_id: int, current_user_id: int | None = None
) -> list[dict[str, Any]]:
    """Blocked participants are excluded from the public projection only."""
    rows = [row for row in await _rows(db, round_id) if not row["is_blocked"]]
    ranked = _sort_and_rank(rows)
    for row in ranked:
        row["is_current_user"] = current_user_id is not None and (
            row["participant_id"] == current_user_id
        )
        row["game_score"] = f"{row['effective_game_score']:.2f}"
        row["stealth_score"] = f"{row['stealth_score']:.2f}"
        row["resource_score"] = f"{row['effective_resource_score']:.2f}"
    return ranked


async def build_admin_leaderboard(
    db: AsyncSession, round_id: int
) -> list[dict[str, Any]]:
    """Admin board keeps blocked participants and shows base vs effective."""
    return _sort_and_rank(await _rows(db, round_id))
