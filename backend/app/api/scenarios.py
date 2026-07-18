from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user
from backend.app.db.session import get_db
from backend.app.domain.enums import RoundStatus, ScenarioStatus
from backend.app.models.entities import Round, Scenario, User
from backend.app.schemas.contracts import ScenarioOut, ScenarioSubmitIn, ScoringResultOut

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.post("/submit", response_model=ScenarioOut)
def submit_scenario(
    payload: ScenarioSubmitIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Scenario:
    round_obj = db.get(Round, payload.round_id)
    if round_obj is None or round_obj.status != RoundStatus.active:
        raise HTTPException(status_code=400, detail="Round is not active")

    scenario = db.scalar(
        select(Scenario).where(
            Scenario.round_id == payload.round_id,
            Scenario.participant_id == current_user.id,
        )
    )
    if scenario is None:
        scenario = Scenario(round_id=payload.round_id, participant_id=current_user.id)
        db.add(scenario)

    scenario.steps = [step.model_dump() for step in payload.steps]
    scenario.status = ScenarioStatus.submitted
    scenario.submitted_at = datetime.utcnow()
    db.commit()
    db.refresh(scenario)
    return scenario


@router.get("/mine/{round_id}", response_model=ScenarioOut | None)
def get_my_scenario(
    round_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Scenario | None:
    return db.scalar(
        select(Scenario).where(
            Scenario.round_id == round_id,
            Scenario.participant_id == current_user.id,
        )
    )


@router.get("/mine/{round_id}/result", response_model=ScoringResultOut | None)
def get_my_result(
    round_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scenario = db.scalar(
        select(Scenario).where(
            Scenario.round_id == round_id,
            Scenario.participant_id == current_user.id,
        )
    )
    if scenario is None:
        return None
    return scenario.result
