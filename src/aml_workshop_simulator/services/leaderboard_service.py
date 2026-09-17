"""Ranking from computed scores; no manual overlays or stored ranks."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.db.models.scoring_results import ScoringResult
from src.aml_workshop_simulator.db.models.users import User
from src.aml_workshop_simulator.schemas.scoring import (
    AMLProbabilityExplanationOut,
    GamePatternExplanationOut,
)
from src.aml_workshop_simulator.domain.scoring import (
    AML_LEADERBOARD_VERSION,
    LEADERBOARD_VERSION,
)


def saved_score_semantics(explanation):
    """Project stored probability; never load a model or infer p from rounded scores."""
    if explanation.get("schema_version") in (4, 5):
        saved = (
            GamePatternExplanationOut
            if explanation["schema_version"] == 5
            else AMLProbabilityExplanationOut
        ).model_validate(explanation)
        return dict(
            score_kind=saved.score_kind,
            aml_probability=saved.aml_probability,
            category=saved.category,
            leaderboard_version=AML_LEADERBOARD_VERSION,
        )
    return dict(
        score_kind="legacy_risk",
        aml_probability=None,
        category=None,
        leaderboard_version=LEADERBOARD_VERSION,
    )


def ranked_scenarios(round_id: int | None = None):
    """Shared dense ranking of eligible participants, independently per round."""
    query = (
        select(
            Scenario.id.label("scenario_id"),
            func.dense_rank()
            .over(
                partition_by=Scenario.round_id,
                order_by=(
                    ScoringResult.game_score.desc(),
                    ScoringResult.risk_score,
                    ScoringResult.resource_score.desc(),
                ),
            )
            .label("rank"),
        )
        .select_from(Scenario)
        .join(ScoringResult, ScoringResult.scenario_id == Scenario.id)
        .join(User, User.id == Scenario.participant_id)
        .where(User.is_blocked.is_(False), Scenario.status == "scored")
    )
    if round_id is not None:
        query = query.where(Scenario.round_id == round_id)
    return query.subquery()


async def build_leaderboard(
    db: AsyncSession,
    round_id: int,
    *,
    include_blocked: bool = False,
    current_user_id: int | None = None,
) -> list[dict[str, Any]]:
    ranks = ranked_scenarios(round_id)
    query = (
        select(Scenario, User, ScoringResult, ranks.c.rank)
        .select_from(Scenario)
        .join(User, Scenario.participant_id == User.id)
        .join(ScoringResult, ScoringResult.scenario_id == Scenario.id)
        .outerjoin(ranks, ranks.c.scenario_id == Scenario.id)
        .where(Scenario.round_id == round_id, Scenario.status == "scored")
    )
    if not include_blocked:
        query = query.where(User.is_blocked.is_(False))
    records = (
        await db.execute(
            query.order_by(
                ScoringResult.game_score.desc(),
                ScoringResult.risk_score,
                ScoringResult.resource_score.desc(),
                Scenario.id,
            )
        )
    ).all()
    rows = []
    for scenario, user, result, rank in records:
        rows.append(
            dict(
                rank=rank,
                scenario_id=scenario.id,
                participant_id=user.id,
                display_name=user.display_name or f"Участник #{user.id}",
                email=user.email,
                is_blocked=user.is_blocked,
                is_current_user=user.id == current_user_id,
                game_score=f"{result.game_score:.2f}",
                risk_score=f"{result.risk_score:.2f}",
                resource_score=f"{result.resource_score:.2f}",
                stealth_score=f"{result.stealth_score:.2f}",
                risk_label=result.risk_label,
                **saved_score_semantics(result.explanation),
            )
        )
    return sorted(rows, key=lambda row: row["is_blocked"])
