from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import require_admin
from backend.app.db.session import get_db
from backend.app.models.entities import Round, Scenario, ScoringResult, User
from backend.app.schemas.contracts import BoardRowOut, RoundCreateIn, RoundOut, RoundStatsOut
from backend.app.services.rounds import activate_round, get_round_stats, score_round

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.post("/rounds", response_model=RoundOut)
def create_round(payload: RoundCreateIn, db: Session = Depends(get_db)) -> Round:
    round_obj = Round(title=payload.title)
    db.add(round_obj)
    db.commit()
    db.refresh(round_obj)
    return round_obj


@router.get("/rounds", response_model=list[RoundOut])
def list_rounds(db: Session = Depends(get_db)) -> list[Round]:
    return list(db.scalars(select(Round).order_by(Round.id.desc())).all())


@router.post("/rounds/{round_id}/activate", response_model=RoundOut)
def activate(round_id: int, db: Session = Depends(get_db)) -> Round:
    try:
        return activate_round(db, round_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/rounds/{round_id}/score")
def run_scoring(round_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        scored_count = score_round(db, round_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"round_id": round_id, "scored_count": scored_count}


@router.get("/rounds/{round_id}/stats", response_model=RoundStatsOut)
def stats(round_id: int, db: Session = Depends(get_db)) -> RoundStatsOut:
    return get_round_stats(db, round_id)


@router.get("/rounds/{round_id}/board", response_model=list[BoardRowOut])
def board(round_id: int, db: Session = Depends(get_db)) -> list[BoardRowOut]:
    rows = db.execute(
        select(
            User.display_name,
            Scenario.id,
            ScoringResult.risk_score,
            ScoringResult.label,
            ScoringResult.explanation,
        )
        .join(Scenario, Scenario.participant_id == User.id)
        .join(ScoringResult, ScoringResult.scenario_id == Scenario.id)
        .where(Scenario.round_id == round_id)
        .order_by(ScoringResult.risk_score.desc())
    ).all()
    return [
        BoardRowOut(
            participant_name=display_name,
            scenario_id=scenario_id,
            risk_score=risk_score,
            label=label,
            top_factors=explanation.get("top_factors", []),
        )
        for display_name, scenario_id, risk_score, label, explanation in rows
    ]
