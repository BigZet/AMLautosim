"""Strict DTO tests: `extra="forbid"`, Decimal money, enum channels."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from src.aml_workshop_simulator.schemas.admin import (
    AccessUpdateIn,
    LeaderboardAdjustmentIn,
    RoundCreateIn,
    RoundUpdateIn,
)
from src.aml_workshop_simulator.schemas.auth import LoginIn, RegisterIn
from src.aml_workshop_simulator.schemas.scenarios import (
    CardRef,
    OperationContext,
    ScenarioPutIn,
    ScenarioStepIn,
    ScenarioSubmitIn,
)

STRICT_INPUT_MODELS: list[type[BaseModel]] = [
    RegisterIn,
    LoginIn,
    CardRef,
    OperationContext,
    ScenarioStepIn,
    ScenarioPutIn,
    ScenarioSubmitIn,
    RoundCreateIn,
    RoundUpdateIn,
    AccessUpdateIn,
    LeaderboardAdjustmentIn,
]


def valid_step_payload(**overrides) -> dict:
    payload = {
        "step_id": str(uuid.uuid4()),
        "card": {"id": 1, "code": "salary", "version": 1},
        "amount": "50000.00",
        "frequency": 1,
        "context": {"channel": "bank"},
        "action_details": {"employer_profile": "verified_employer"},
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("model", STRICT_INPUT_MODELS, ids=lambda m: m.__name__)
def test_every_input_model_forbids_extra_fields(model: type[BaseModel]) -> None:
    assert model.model_config.get("extra") == "forbid"


def test_step_accepts_a_well_formed_payload() -> None:
    step = ScenarioStepIn.model_validate(valid_step_payload())
    assert step.amount == Decimal("50000.00")
    assert step.context.channel == "bank"


def test_step_rejects_unknown_top_level_field() -> None:
    with pytest.raises(ValidationError):
        ScenarioStepIn.model_validate(valid_step_payload(card_code="salary"))


def test_step_rejects_unknown_context_field() -> None:
    with pytest.raises(ValidationError):
        ScenarioStepIn.model_validate(
            valid_step_payload(context={"channel": "bank", "mood": "calm"})
        )


def test_channel_may_be_omitted_and_must_otherwise_be_a_known_value() -> None:
    """An omitted channel is filled from the round policy, not guessed here."""
    omitted = ScenarioStepIn.model_validate(valid_step_payload(context={}))
    assert omitted.context.channel is None

    with pytest.raises(ValidationError) as raised:
        ScenarioStepIn.model_validate(valid_step_payload(context={"channel": "carrier_pigeon"}))
    assert "channel" in str(raised.value)


def test_optional_context_fields_default_to_not_sent() -> None:
    step = ScenarioStepIn.model_validate(valid_step_payload(context={"channel": "bank"}))
    assert step.context.time_of_day is None
    assert step.context.has_documents is None

    payload = valid_step_payload(context={"channel": "bank"})
    payload.pop("frequency")
    assert ScenarioStepIn.model_validate(payload).frequency is None


@pytest.mark.parametrize("channel", ["bank", "branch", "atm", "mobile", "web", "exchange", "pos"])
def test_every_known_channel_passes_the_schema(channel: str) -> None:
    step = ScenarioStepIn.model_validate(valid_step_payload(context={"channel": channel}))
    assert step.context.channel == channel


def test_money_is_decimal_and_rejects_specials() -> None:
    for bad in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(ValidationError):
            ScenarioStepIn.model_validate(valid_step_payload(amount=bad))
    with pytest.raises(ValidationError):
        ScenarioStepIn.model_validate(valid_step_payload(amount="0.00"))
    with pytest.raises(ValidationError):
        ScenarioStepIn.model_validate(valid_step_payload(amount="-1.00"))
    with pytest.raises(ValidationError):
        ScenarioStepIn.model_validate(valid_step_payload(amount="10.123"))


def test_frequency_bounds() -> None:
    with pytest.raises(ValidationError):
        ScenarioStepIn.model_validate(valid_step_payload(frequency=0))
    with pytest.raises(ValidationError):
        ScenarioStepIn.model_validate(valid_step_payload(frequency=21))
    assert ScenarioStepIn.model_validate(valid_step_payload(frequency=20)).frequency == 20


def test_step_id_must_be_a_uuid() -> None:
    with pytest.raises(ValidationError):
        ScenarioStepIn.model_validate(valid_step_payload(step_id="step-1"))


def test_card_version_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        ScenarioStepIn.model_validate(
            valid_step_payload(card={"id": 1, "code": "salary", "version": 0})
        )


def test_action_details_reject_nested_objects() -> None:
    with pytest.raises(ValidationError):
        ScenarioStepIn.model_validate(
            valid_step_payload(action_details={"employer_profile": {"nested": True}})
        )


def test_put_requires_a_client_mutation_id() -> None:
    with pytest.raises(ValidationError):
        ScenarioPutIn.model_validate({"expected_revision": 0, "steps": []})
    payload = ScenarioPutIn.model_validate(
        {
            "expected_revision": 0,
            "client_mutation_id": str(uuid.uuid4()),
            "steps": [],
        }
    )
    assert payload.steps == []


def test_submit_requires_a_stored_revision() -> None:
    with pytest.raises(ValidationError):
        ScenarioSubmitIn.model_validate({"expected_revision": 0})
    assert ScenarioSubmitIn.model_validate({"expected_revision": 3}).expected_revision == 3


def test_registration_password_policy() -> None:
    base = {"email": "a@example.com", "display_name": "Игрок"}
    with pytest.raises(ValidationError):
        RegisterIn.model_validate({**base, "password": "short1234"})
    assert RegisterIn.model_validate({**base, "password": "0123456789"}).password


def test_registration_rejects_a_role_field() -> None:
    with pytest.raises(ValidationError):
        RegisterIn.model_validate(
            {
                "email": "a@example.com",
                "display_name": "Игрок",
                "password": "0123456789",
                "role": "admin",
            }
        )


def test_adjustment_overrides_are_bounded() -> None:
    with pytest.raises(ValidationError):
        LeaderboardAdjustmentIn.model_validate(
            {"expected_revision": 0, "game_score_override": "120", "reason": "техническая ошибка"}
        )
    assert LeaderboardAdjustmentIn.model_validate(
        {"expected_revision": 0, "game_score_override": "75.5", "reason": "техническая ошибка"}
    ).game_score_override == Decimal("75.5")


def test_access_update_requires_a_meaningful_reason() -> None:
    with pytest.raises(ValidationError):
        AccessUpdateIn.model_validate(
            {"blocked": True, "reason": "нет", "expected_access_revision": 1}
        )
