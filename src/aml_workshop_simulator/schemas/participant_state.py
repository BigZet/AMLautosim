"""One consistent response for the participant screen."""

from pydantic import BaseModel

from src.aml_workshop_simulator.schemas.leaderboard import ResultOut
from src.aml_workshop_simulator.schemas.rounds import RoundPublicOut
from src.aml_workshop_simulator.schemas.scenarios import ScenarioOut


class ParticipantStateOut(BaseModel):
    round: RoundPublicOut | None = None
    scenario: ScenarioOut | None = None
    result: ResultOut | None = None
    can_edit: bool = False
    can_submit: bool = False
    can_view_leaderboard: bool = False
