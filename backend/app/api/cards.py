from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_user
from backend.app.db.session import get_db
from backend.app.models.entities import ActionCard
from backend.app.schemas.contracts import ActionCardOut

router = APIRouter(prefix="/cards", tags=["cards"])


@router.get("", response_model=list[ActionCardOut])
def list_cards(
    db: Session = Depends(get_db),
    _current_user=Depends(get_current_user),
) -> list[ActionCard]:
    return list(
        db.scalars(select(ActionCard).where(ActionCard.is_active.is_(True)).order_by(ActionCard.id)).all()
    )
