"""Read participant state from one PostgreSQL statement, without row locks."""

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.core.errors import NotFound
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.db.models.scoring_results import ScoringResult
from src.aml_workshop_simulator.schemas.leaderboard import BaseResultOut, ResultOut
from src.aml_workshop_simulator.schemas.participant_state import ParticipantStateOut
from src.aml_workshop_simulator.schemas.rounds import RoundPublicOut
from src.aml_workshop_simulator.services.leaderboard_service import ranked_scenarios
from src.aml_workshop_simulator.services.projections import scenario_out


def public_round_out(row: Round) -> RoundPublicOut:
    return RoundPublicOut(
        **{
            key: getattr(row, key)
            for key in RoundPublicOut.model_fields
            if key != "config_version"
        },
        config_version=row.game_config["config_version"],
    )


async def current_round(db: AsyncSession) -> RoundPublicOut | None:
    row = (await db.execute(select(Round))).scalar_one_or_none()
    return public_round_out(row) if row else None


async def read(
    db: AsyncSession,
    participant_id: int,
    round_id: int | None = None,
) -> ParticipantStateOut:
    # Filtering the participant happens outside the ranking subquery. Otherwise
    # a window function would incorrectly assign every participant first place.
    ranks = ranked_scenarios(round_id)
    query = (
        select(Round, Scenario, ScoringResult, ranks.c.rank)
        .select_from(Round)
        .outerjoin(
            Scenario,
            and_(
                Scenario.round_id == Round.id, Scenario.participant_id == participant_id
            ),
        )
        .outerjoin(ScoringResult, ScoringResult.scenario_id == Scenario.id)
        .outerjoin(ranks, ranks.c.scenario_id == Scenario.id)
    )
    if round_id is not None:
        query = query.where(Round.id == round_id)
    record = (
        await db.execute(query.execution_options(populate_existing=True))
    ).one_or_none()
    if record is None:
        if round_id is not None:
            raise NotFound("Раунд не найден или перезапущен.", code="round_not_found")
        return ParticipantStateOut()
    row, scenario, scored, rank = record
    visible = (
        scenario is not None
        and row.status != "draft"
        and (scenario.status != "editing" or row.status == "active")
    )
    own = scenario_out(scenario) if visible else None
    result = None
    if (
        row.status == "completed"
        and own is not None
        and scenario.status == "scored"
        and scored is not None
    ):
        result = ResultOut(
            scenario_id=scenario.id,
            scores=BaseResultOut(
                **{key: str(getattr(scored, key)) for key in BaseResultOut.model_fields}
            ),
            rank=rank,
            explanation=scored.explanation,
            resources=scenario.resource_snapshot,
        )
    return ParticipantStateOut(
        round=public_round_out(row),
        scenario=own,
        result=result,
        can_edit=row.status == "active"
        and (scenario is None or scenario.status == "editing"),
        can_submit=own.can_submit if own is not None else False,
        can_view_leaderboard=row.status == "completed",
    )
