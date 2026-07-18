from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user
from backend.app.db.session import get_db
from backend.app.schemas.contracts import RoundOut
from backend.app.services.rounds import get_active_round

router = APIRouter(prefix="/rounds", tags=["rounds"])


@router.get("/active", response_model=RoundOut | None)
def active_round(db: Session = Depends(get_db), _current_user=Depends(get_current_user)):
    return get_active_round(db)
