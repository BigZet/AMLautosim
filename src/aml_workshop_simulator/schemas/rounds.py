from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from src.aml_workshop_simulator.schemas.history_summary import RoundContextOut
from src.aml_workshop_simulator.core.enums import RoundStatus
from src.aml_workshop_simulator.domain.contract_versions import is_playable_contract
from src.aml_workshop_simulator.schemas.card_contract import (
    CardCostsOut,
    OptionOut,
    ParameterOut,
    ParameterValue,
)
from src.aml_workshop_simulator.schemas.round_config import RoundConfigOutput


class RoundPublicOut(RoundContextOut):
    """Non-secret round configuration for the participant UI."""

    id: int
    title: str
    status: RoundStatus
    config_version: str | None = None
    activated_at: datetime | None = None
    closed_at: datetime | None = None
    scoring_started_at: datetime | None = None
    completed_at: datetime | None = None
    game_config: RoundConfigOutput

    @computed_field
    @property
    def accepts_changes(self) -> bool:
        return self.status == "active" and is_playable_contract(
            self.game_config.model_dump(mode="json")
        )


class VisibleParamOut(BaseModel):
    """One control the participant is actually offered for an operation."""

    param: str
    key: str
    namespace: Literal["channel", "context", "action"]
    label: str
    kind: str = "select"
    help: str | None = None
    default: ParameterValue | None = None
    options: list[OptionOut] = Field(default_factory=list)


class ActionCardOut(BaseModel):
    """One immutable card version plus its round-resolved UI contract.

    `channels`, `fields` and `context_fields` come from the very
    `parameter_schema` the server validates against, so the UI cannot offer an
    option the API would reject. `visible_params` contains all declared fields
    in display order; `pinned_defaults` is empty.
    """

    id: int
    code: str
    version: int
    title: str
    description: str = ""
    category: str
    flow: str
    risk_weight: str
    costs: CardCostsOut
    fee_rate: str
    min_amount: str
    max_amount: str
    max_occurrences: int
    requires_card_code: str | None = None
    quota_category: str | None = None
    channels: list[str] = Field(default_factory=list)
    channel_labels: dict[str, str] = Field(default_factory=dict)
    fields: list[ParameterOut] = Field(default_factory=list)
    context_fields: list[ParameterOut] = Field(default_factory=list)
    visible_params: list[VisibleParamOut] = Field(default_factory=list)
    pinned_defaults: dict[str, ParameterValue] = Field(default_factory=dict)
