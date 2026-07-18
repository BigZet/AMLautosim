from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.entities import (
    ActionCard,
    Round,
    Scenario,
    ScoringResult,
    User,
)
from backend.app.domain.enums import RoundStatus, ScenarioStatus, UserRole
from backend.app.schemas.contracts import RoundStatsOut
from backend.app.services.scoring import score_steps


def get_active_round(db: Session) -> Round | None:
    return db.scalar(select(Round).where(Round.status == RoundStatus.active).order_by(Round.id.desc()))


def activate_round(db: Session, round_id: int) -> Round:
    for item in db.scalars(select(Round).where(Round.status == RoundStatus.active)).all():
        item.status = RoundStatus.completed
        item.completed_at = datetime.utcnow()

    round_obj = db.get(Round, round_id)
    if round_obj is None:
        raise ValueError("Round not found")
    round_obj.status = RoundStatus.active
    round_obj.started_at = datetime.utcnow()
    db.commit()
    db.refresh(round_obj)
    return round_obj


def score_round(db: Session, round_id: int) -> int:
    round_obj = db.get(Round, round_id)
    if round_obj is None:
        raise ValueError("Round not found")

    round_obj.status = RoundStatus.scoring
    db.flush()

    card_weights = {card.code: card.risk_weight for card in db.scalars(select(ActionCard)).all()}
    scenarios = db.scalars(
        select(Scenario).where(
            Scenario.round_id == round_id,
            Scenario.status.in_([ScenarioStatus.submitted, ScenarioStatus.scored]),
        )
    ).all()

    scored_count = 0
    for scenario in scenarios:
        risk_score, label, explanation = score_steps(scenario.steps, card_weights)
        result = db.scalar(select(ScoringResult).where(ScoringResult.scenario_id == scenario.id))
        if result is None:
            result = ScoringResult(scenario_id=scenario.id, risk_score=risk_score, label=label)
            db.add(result)
        result.risk_score = risk_score
        result.label = label
        result.explanation = explanation
        scenario.status = ScenarioStatus.scored
        scored_count += 1

    round_obj.status = RoundStatus.completed
    round_obj.completed_at = datetime.utcnow()
    db.commit()
    return scored_count


def get_round_stats(db: Session, round_id: int) -> RoundStatsOut:
    registered_users = db.scalar(
        select(func.count()).select_from(User).where(User.role == UserRole.participant)
    ) or 0
    submitted_scenarios = db.scalar(
        select(func.count()).select_from(Scenario).where(Scenario.round_id == round_id)
    ) or 0
    scored_scenarios = db.scalar(
        select(func.count())
        .select_from(Scenario)
        .where(Scenario.round_id == round_id, Scenario.status == ScenarioStatus.scored)
    ) or 0
    return RoundStatsOut(
        round_id=round_id,
        registered_users=registered_users,
        submitted_scenarios=submitted_scenarios,
        scored_scenarios=scored_scenarios,
    )
