"""Versioned v8 shapes for released rounds and earlier development snapshots.

Party references, timeline and versioned observed history are validated here. Playable entrypoints require the pinned v8 model contract.
"""

from datetime import timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
    model_serializer,
)

from src.aml_workshop_simulator.schemas.scenarios import (
    ExpandedScenarioStepIn as ExpandedScenarioStepIn,
)

Identifier = Annotated[str, Field(min_length=1, max_length=80)]
Amount = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]
Interval = Literal[1, 10, 60, 1440]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Counterparty(ContractModel):
    id: Identifier
    name: str = Field(min_length=1, max_length=160)
    kind: Literal["person", "merchant", "institution"]
    information_status: Literal["sufficient", "limited", "unknown"]
    personal_relationship: Literal["known", "unknown"]
    category: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("name", mode="before")
    @classmethod
    def meaningful_name(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError(
                    "Укажите название стороны: одних пробелов недостаточно"
                )
        return value


class ClientProfile(ContractModel):
    id: Identifier
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)


class HistoricalOperation(ContractModel):
    id: Identifier
    occurred_at: AwareDatetime
    operation_code: Literal[
        "salary", "incoming_transfer", "card_transfer", "cash_withdrawal", "purchase"
    ]
    amount: Amount
    counterparty_id: Identifier | None = None
    category: str | None = Field(default=None, min_length=1, max_length=80)


class History(ContractModel):
    version: Literal["observed-history-v1"] | None = None

    @model_serializer(mode="wrap")
    def _legacy_shape(self, handler):
        value = handler(self)
        if self.version is None:
            value.pop("version", None)
        return value

    # None represents unavailable history; [] means observed inactivity.
    window_days: Literal[30]
    operations: list[HistoricalOperation] | None = Field(max_length=10000)


class Timeline(ContractModel):
    version: Literal["operation-timeline-v1"] = "operation-timeline-v1"
    starts_at: AwareDatetime
    timezone: str = Field(min_length=1, max_length=80)
    waiting_costs: dict[Interval, int]

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Неизвестный часовой пояс") from error
        return value

    @field_validator("waiting_costs", mode="before")
    @classmethod
    def _json_cost_keys(cls, value):
        if isinstance(value, dict):
            return {
                int(k)
                if isinstance(k, str) and k in {"1", "10", "60", "1440"}
                else k: v
                for k, v in value.items()
            }
        return value

    @field_validator("waiting_costs")
    @classmethod
    def _fixed_initial_costs(cls, value):
        if value != {1: 0, 10: 1, 60: 2, 1440: 4}:
            raise ValueError("Контракт v8: интервалы 1/10/60/1440 стоят 0/1/2/4")
        return value


class TurnoverPolicy(ContractModel):
    target_operation_codes: tuple[Literal["card_transfer"], Literal["cash_withdrawal"]]


class PurchasePolicy(ContractModel):
    version: Literal["purchase-policy-v1", "purchase-policy-v2"] = "purchase-policy-v1"
    max_total: Decimal = Field(
        default=Decimal("30000.00"), ge=0, le=1000000000, decimal_places=2
    )

    @model_validator(mode="after")
    def legacy_total(self):
        if self.version == "purchase-policy-v1" and self.max_total != Decimal("30000.00"):
            raise ValueError("purchase-policy-v1 fixes the total at 30000")
        return self


class ExpandedBehavior(ContractModel):
    sender_policy: Literal["separate-employer-v1"] | None = None
    release: Literal["expanded-game-v1"] | None = None
    counterparties: list[Counterparty] = Field(min_length=1, max_length=100)
    profile: ClientProfile
    history: History
    timeline: Timeline
    turnover: TurnoverPolicy
    purchases: PurchasePolicy | None = None

    @model_serializer(mode="wrap")
    def _legacy_release_shape(self, handler):
        value = handler(self)
        if self.release is None:
            value.pop("release", None)
        if self.sender_policy is None:
            value.pop("sender_policy", None)
        return value

    @model_validator(mode="after")
    def _unique_parties_and_history_references(self):
        ids = [party.id for party in self.counterparties]
        if len(ids) != len(set(ids)):
            raise ValueError("ID сторон должны быть уникальны в снимке раунда")
        for operation in self.history.operations or []:
            if (
                operation.counterparty_id is not None
                and operation.counterparty_id not in ids
            ):
                raise ValueError("История ссылается на сторону вне каталога раунда")
        if self.release is not None and (
            self.history.version is None or self.purchases is None
        ):
            raise ValueError(
                "Расширенная игра требует версионированные историю и покупки"
            )
        if self.history.version is not None:
            self._validate_observed_history()
        return self

    def _validate_observed_history(self):
        from src.aml_workshop_simulator.domain.counterparty_roles import (
            PARTY_ROLES,
            party_allowed,
        )

        end = self.timeline.starts_at.astimezone(timezone.utc)
        start = end - timedelta(days=30)
        parties = {party.id: party for party in self.counterparties}
        seen = set()
        for operation in self.history.operations or []:
            if operation.id in seen:
                raise ValueError("ID событий истории должны быть уникальны")
            seen.add(operation.id)
            if not start <= operation.occurred_at.astimezone(timezone.utc) < end:
                raise ValueError(
                    "История должна находиться в 30 днях до начала сценария"
                )
            role, kinds = PARTY_ROLES[operation.operation_code]
            party = parties.get(operation.counterparty_id)
            if role is None:
                if operation.counterparty_id is not None:
                    raise ValueError("Снятие наличных в истории не имеет контрагента")
            elif party is None or not party_allowed(
                operation.operation_code, party, self.sender_policy
            ):
                raise ValueError("Неподходящая сторона исторической операции")
            expected = (
                party.category if operation.operation_code == "purchase" else None
            )
            if operation.category is not None and operation.category != expected:
                raise ValueError(
                    "Категория истории должна соответствовать торговой стороне"
                )


class ExpandedTurnoverTotals(ContractModel):
    """Reserved result shape; v7 totals are not silently renamed."""

    gross_inflow: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    gross_outflow: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    target_outflow: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    fees: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
