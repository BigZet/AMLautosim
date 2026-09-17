"""Read-only, derived round context; never accepted as configuration input."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, computed_field, model_serializer

from src.aml_workshop_simulator.schemas.round_config import RoundConfigOutput


class ActivitySummary(BaseModel):
    count: int
    inflow: Decimal
    outflow: Decimal


class PartyHistorySummary(BaseModel):
    activity: ActivitySummary | None
    counterparty_id: str
    observation: Literal["observed", "absent", "unknown"]
    first_at: datetime | None
    last_at: datetime | None


class HistoryEventOut(BaseModel):
    id: str
    occurred_at: datetime
    operation_code: str
    amount: Decimal
    counterparty_id: str | None
    category: str | None
    incoming_kind: str | None = None
    bank_country: str | None = None
    channel: str | None = None
    income_basis: str | None = None


class HistorySummaryOut(BaseModel):
    version: Literal["history-summary-v1"] = "history-summary-v1"
    status: Literal["observed", "unknown"]
    starts_at: datetime
    ends_before: datetime
    timezone: str
    activity: ActivitySummary | None
    active_days: int | None
    unique_counterparties: int | None
    by_operation: dict[str, ActivitySummary] | None
    counterparties: list[PartyHistorySummary]
    events: list[HistoryEventOut] | None
    coverage: Literal["complete", "partial", "unknown"] | None = None

    @model_serializer(mode="wrap")
    def legacy_shape(self, handler):
        value = handler(self)
        if self.coverage is None:
            value.pop("coverage", None)
        return value


class RoundContextOut(BaseModel):
    game_config: RoundConfigOutput

    @computed_field
    @property
    def context_summary(self) -> HistorySummaryOut | None:
        from src.aml_workshop_simulator.services.profile_history import history_summary

        if self.game_config.schema_version not in (8, 9, 10):
            return None
        return history_summary(self.game_config.behavior)

    @model_serializer(mode="wrap")
    def _legacy_shape(self, handler):
        value = handler(self)
        if value.get("context_summary") is None:
            value.pop("context_summary", None)
        return value
