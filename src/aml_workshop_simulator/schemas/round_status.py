from typing import Literal

from pydantic import BaseModel


class RoundStatusOut(BaseModel):
    round_id: int | None = None
    status: Literal['none', 'draft', 'active', 'closed', 'scoring', 'completed'] = 'none'
    config_version: str | None = None
    scenario_revision: int = 0
    access_revision: int = 0
    results_version: str
