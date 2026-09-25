"""Read participant state from one PostgreSQL statement, without row locks."""

import hashlib
import json
from functools import lru_cache

from sqlalchemy import and_, select, func, true
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from src.aml_workshop_simulator.core.errors import NotFound
from src.aml_workshop_simulator.domain.contract_versions import is_playable_contract
from src.aml_workshop_simulator.db.models.rounds import Round
from src.aml_workshop_simulator.db.models.users import User
from src.aml_workshop_simulator.db.models.scenarios import Scenario
from src.aml_workshop_simulator.db.models.scoring_results import ScoringResult
from src.aml_workshop_simulator.schemas.leaderboard import BaseResultOut, ResultOut
from src.aml_workshop_simulator.schemas.participant_state import ParticipantStateOut
from src.aml_workshop_simulator.schemas.rounds import RoundPublicOut
from src.aml_workshop_simulator.schemas.round_config import parse_game_config
from src.aml_workshop_simulator.services.leaderboard_service import ranked_scenarios
from src.aml_workshop_simulator.services.projections import scenario_out
from src.aml_workshop_simulator.schemas.round_status import RoundStatusOut


def access_version_query():
    users = aliased(User)
    return select(func.coalesce(func.sum(users.access_revision), 0)).where(users.role == 'participant').correlate(None).scalar_subquery()


def publication_version(round_id, completed_at, access_version):
    return hashlib.sha256(f'{round_id}:{completed_at}:{access_version}'.encode()).hexdigest()


async def results_version(db, row):
    access = (await db.execute(select(access_version_query()))).scalar_one()
    return publication_version(row.id, row.completed_at, access)


async def status(db: AsyncSession, participant_id: int) -> RoundStatusOut:
    record = (await db.execute(
        select(User.access_revision, Round.id, Round.status,
               Round.game_config['config_version'].as_string(), Scenario.revision,
               Round.completed_at, access_version_query())
        .select_from(User).outerjoin(Round, true())
        .outerjoin(Scenario, and_(Scenario.round_id == Round.id, Scenario.participant_id == User.id))
        .where(User.id == participant_id)
    )).one()
    access, round_id, phase, config, revision, completed, version = record
    return RoundStatusOut(round_id=round_id, status=phase or 'none', config_version=config,
                          scenario_revision=revision or 0, access_revision=access,
                          results_version=publication_version(round_id, completed, version))


@lru_cache(maxsize=64)
def _validated_config(round_id, version, serialized):
    return parse_game_config(json.loads(serialized), stored=True)


def public_round_out(row: Round) -> RoundPublicOut:
    return RoundPublicOut(
        **{
            key: getattr(row, key)
            for key in RoundPublicOut.model_fields
            if key not in {"config_version", "game_config"}
        },
        config_version=row.game_config["config_version"],
        game_config=_validated_config(row.id, row.game_config['config_version'],
                                      json.dumps(row.game_config, sort_keys=True)).model_copy(deep=True),
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
        can_edit=is_playable_contract(row.game_config)
        and row.status == "active"
        and (scenario is None or scenario.status == "editing"),
        can_submit=(own.can_submit and is_playable_contract(row.game_config))
        if own is not None
        else False,
        can_view_leaderboard=row.status == "completed",
    )
