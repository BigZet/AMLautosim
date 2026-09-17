"""Observable, server-owned evidence for the v10 educational population."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from src.aml_workshop_simulator.schemas.expanded_contract import ContractModel, Identifier
from src.aml_workshop_simulator.schemas.scenarios import PurposeCode

Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2, allow_inf_nan=False)]
OperationCode = Literal["salary", "incoming_transfer", "card_transfer", "cash_withdrawal", "purchase"]
VerificationStatus = Literal["verified", "unverified", "contradicted", "unknown"]


class ExpectedActivity(ContractModel):
    period_start: AwareDatetime
    period_end: AwareDatetime
    activity_kinds: list[PurposeCode] = Field(min_length=1, max_length=9)
    expected_credit_min: Money | None = None
    expected_credit_max: Money | None = None
    expected_debit_min: Money | None = None
    expected_debit_max: Money | None = None

    @model_validator(mode="after")
    def coherent_ranges(self):
        if self.period_start >= self.period_end:
            raise ValueError("Expected activity period must have positive duration")
        if len(self.activity_kinds) != len(set(self.activity_kinds)):
            raise ValueError("Expected activity kinds must be unique")
        for direction in ("credit", "debit"):
            lo = getattr(self, f"expected_{direction}_min")
            hi = getattr(self, f"expected_{direction}_max")
            if (lo is None) != (hi is None) or (lo is not None and lo > hi):
                raise ValueError("Expected amount range requires both limits and min <= max")
        return self


class Purpose(ContractModel):
    code: PurposeCode
    title: str = Field(min_length=1, max_length=160)


class EvidenceFact(ContractModel):
    id: Identifier
    fact_type: Literal["source_of_funds", "payment_purpose", "relationship", "opening_balance"]
    verification_status: VerificationStatus
    provenance: Literal["scenario_record", "customer_statement", "independent_record"]
    available_at: AwareDatetime
    valid_from: AwareDatetime
    valid_to: AwareDatetime
    counterparty_ids: list[Identifier] = Field(max_length=100)
    operation_codes: list[OperationCode] = Field(max_length=5)
    purpose_code: PurposeCode
    max_credit_amount: Money
    max_debit_amount: Money

    @model_validator(mode="after")
    def coherent_scope(self):
        if self.valid_from > self.valid_to:
            raise ValueError("Evidence validity range is reversed")
        for values in (self.counterparty_ids, self.operation_codes):
            if len(values) != len(set(values)):
                raise ValueError("Evidence scope references must be unique")
        if self.fact_type != "opening_balance" and not self.operation_codes:
            raise ValueError("Transaction evidence requires operation scope")
        return self


class AMLContext(ContractModel):
    version: Literal["aml-context-v1"]
    as_of: AwareDatetime
    expected_activity: ExpectedActivity
    opening_balance_facts: list[Identifier] = Field(max_length=100)
    purpose_catalog: list[Purpose] = Field(min_length=1, max_length=9)
    facts: list[EvidenceFact] = Field(max_length=1000)
    history_coverage: Literal["complete", "partial", "unknown"]
    history_start: AwareDatetime | None = None
    history_end: AwareDatetime | None = None

    @model_validator(mode="after")
    def coherent_references(self):
        ids = [f.id for f in self.facts]
        codes = [p.code for p in self.purpose_catalog]
        if len(ids) != len(set(ids)) or len(codes) != len(set(codes)):
            raise ValueError("Evidence IDs and purpose codes must be unique")
        if len(self.opening_balance_facts) != len(set(self.opening_balance_facts)):
            raise ValueError("Opening balance references must be unique")
        by_id = {f.id: f for f in self.facts}
        for ref in self.opening_balance_facts:
            if ref not in by_id or by_id[ref].fact_type != "opening_balance":
                raise ValueError("Opening balance reference must identify an opening_balance fact")
        for fact in self.facts:
            if fact.purpose_code not in codes:
                raise ValueError("Evidence purpose is outside purpose catalog")
        if any(code not in codes for code in self.expected_activity.activity_kinds):
            raise ValueError("Expected activity purpose is outside purpose catalog")
        if self.history_coverage == "unknown":
            if self.history_start is not None or self.history_end is not None:
                raise ValueError("Unknown history must not invent coverage bounds")
        elif self.history_start is None or self.history_end is None or self.history_start >= self.history_end:
            raise ValueError("Known history requires an ordered coverage range")
        return self
