"""Common documented error contract."""

from pydantic import BaseModel

from src.aml_workshop_simulator.core.enums import RoundStatus
from src.aml_workshop_simulator.schemas.game_state import ViolationOut


class ErrorDetails(BaseModel):
    violations: list[ViolationOut] | None = None
    round_status: RoundStatus | None = None
    current_revision: int | None = None
    current_config_revision: int | None = None
    current_access_revision: int | None = None


class ErrorEnvelope(BaseModel):
    code: str
    message: str
    details: ErrorDetails | None = None
    request_id: str | None = None
