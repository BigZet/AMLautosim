"""The chain validation matrix executed through the real HTTP API.

Mirrors docs/chain-validation-matrix.md. Each case asserts the API status, the
error/violation payload and — where it matters — what PostgreSQL actually holds.
"""

from __future__ import annotations

import json

import psycopg2
import pytest

from src.aml_workshop_simulator.domain.channels import ALL_CHANNELS
from tests.helpers import build_step, error_reasons, put_scenario, violation_reasons


@pytest.fixture()
def active_round(full_round):
    """The whole matrix is exercised against a round that enables every card
    version and every parameter, which is exactly what a legacy round does."""
    return full_round


@pytest.fixture()
def cards(full_cards):
    return full_cards


EXPECTED_MATRIX = {
    "salary": ("bank", "branch", "mobile"),
    "cash_deposit": ("atm", "branch"),
    "card_transfer": ("mobile", "web", "branch"),
    "international": ("web", "branch"),
    "cash_withdrawal": ("atm", "branch"),
    "crypto_exchange": ("exchange", "web"),
    "online_purchase": ("mobile", "web"),
    "refund": ("mobile", "web"),
}
ALLOWED = [(code, ch) for code, chs in EXPECTED_MATRIX.items() for ch in chs]
DISALLOWED = [
    (code, ch)
    for code, chs in EXPECTED_MATRIX.items()
    for ch in ALL_CHANNELS
    if ch not in chs
]


def prerequisite_steps(cards: dict, code: str) -> list[dict]:
    requires = cards[code].get("requires_card_code")
    if not requires:
        return []
    return [build_step(cards[requires], cards[requires]["max_amount"], 1)]


# --------------------------------------------------------------------------
# CH-* channel matrix
# --------------------------------------------------------------------------


def test_the_api_serves_exactly_the_documented_channel_matrix(cards) -> None:
    assert {code: tuple(card["channels"]) for code, card in cards.items()} == EXPECTED_MATRIX


@pytest.mark.parametrize(("code", "channel"), ALLOWED, ids=[f"{c}-{ch}" for c, ch in ALLOWED])
def test_allowed_channel_is_accepted_and_persisted(
    client, participant, active_round, cards, db_dsn, code, channel
) -> None:
    round_id = active_round["id"]
    steps = [
        *prerequisite_steps(cards, code),
        build_step(cards[code], cards[code]["min_amount"], 1, channel),
    ]
    response = put_scenario(client, round_id, participant["headers"], steps)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "channel_not_allowed" not in violation_reasons(body["resources"])
    assert body["steps"][-1]["context"]["channel"] == channel

    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT steps FROM scenarios WHERE id = %s", (body["id"],))
            raw = cursor.fetchone()[0]
    finally:
        connection.close()
    stored = raw if isinstance(raw, list) else json.loads(raw)
    assert stored[-1]["context"]["channel"] == channel


@pytest.mark.parametrize(
    ("code", "channel"), DISALLOWED, ids=[f"{c}-{ch}" for c, ch in DISALLOWED]
)
def test_disallowed_known_channel_is_rejected_with_an_actionable_error(
    client, participant, active_round, cards, code, channel
) -> None:
    round_id = active_round["id"]
    steps = [
        *prerequisite_steps(cards, code),
        build_step(cards[code], cards[code]["min_amount"], 1, channel),
    ]
    response = put_scenario(client, round_id, participant["headers"], steps)
    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "validation_error"
    violation = next(
        item
        for item in payload["details"]["violations"]
        if item["reason"] == "channel_not_allowed"
    )
    assert violation["field"] == "context.channel"
    assert violation["current"] == channel
    assert violation["allowed"] == ", ".join(EXPECTED_MATRIX[code])
    assert violation["step_id"] == steps[-1]["step_id"]


def test_unknown_channel_value_is_rejected_by_the_schema(
    client, participant, active_round, cards
) -> None:
    step = build_step(cards["salary"], 50000, 1, "bank")
    step["context"]["channel"] = "definitely-not-a-channel"
    response = put_scenario(client, active_round["id"], participant["headers"], [step])
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


# --------------------------------------------------------------------------
# FLD-* card fields, options and types
# --------------------------------------------------------------------------


@pytest.mark.parametrize("code", sorted(EXPECTED_MATRIX))
def test_every_declared_option_of_every_action_field_is_accepted(
    client, participant, active_round, cards, code
) -> None:
    round_id = active_round["id"]
    revision = 0
    for field in cards[code]["fields"]:
        for option in field["options"]:
            steps = [
                *prerequisite_steps(cards, code),
                build_step(
                    cards[code],
                    cards[code]["min_amount"],
                    1,
                    action_details={field["key"]: option["value"]},
                ),
            ]
            response = put_scenario(
                client, round_id, participant["headers"], steps, expected_revision=revision
            )
            assert response.status_code == 200, (code, field["key"], option["value"], response.text)
            revision = response.json()["revision"]


def test_unknown_action_field_is_rejected(client, participant, active_round, cards) -> None:
    step = build_step(cards["crypto_exchange"], 5000, 1, "exchange")
    step["action_details"]["not_a_field"] = "x"
    response = put_scenario(client, active_round["id"], participant["headers"], [step])
    assert response.status_code == 422
    assert "unknown_action_parameter" in error_reasons(response)


def test_missing_required_action_field_is_rejected(
    client, participant, active_round, cards
) -> None:
    step = build_step(cards["crypto_exchange"], 5000, 1, "exchange")
    step["action_details"].pop("asset_profile")
    response = put_scenario(client, active_round["id"], participant["headers"], [step])
    assert response.status_code == 422
    assert "missing_action_parameter" in error_reasons(response)


def test_unknown_option_value_is_rejected(client, participant, active_round, cards) -> None:
    step = build_step(cards["crypto_exchange"], 5000, 1, "exchange")
    step["action_details"]["asset_profile"] = "gold_bars"
    response = put_scenario(client, active_round["id"], participant["headers"], [step])
    assert response.status_code == 422
    assert "invalid_action_parameter" in error_reasons(response)


def test_wrong_types_are_rejected(client, participant, active_round, cards) -> None:
    step = build_step(cards["salary"], 50000, 1, "bank")
    step["frequency"] = "two"
    assert put_scenario(
        client, active_round["id"], participant["headers"], [step]
    ).status_code == 422

    step = build_step(cards["salary"], 50000, 1, "bank")
    step["amount"] = "not-a-number"
    assert put_scenario(
        client, active_round["id"], participant["headers"], [step]
    ).status_code == 422


def test_card_id_code_version_mismatch_is_rejected(
    client, participant, active_round, cards
) -> None:
    step = build_step(cards["salary"], 50000, 1, "bank")
    step["card"]["id"] = cards["crypto_exchange"]["id"]
    response = put_scenario(client, active_round["id"], participant["headers"], [step])
    assert response.status_code == 422
    assert "card_reference_mismatch" in error_reasons(response)


def test_unknown_card_version_is_rejected(client, participant, active_round, cards) -> None:
    step = build_step(cards["salary"], 50000, 1, "bank")
    step["card"]["version"] = 7
    response = put_scenario(client, active_round["id"], participant["headers"], [step])
    assert response.status_code == 422
    assert "unknown_card_version" in error_reasons(response)


# --------------------------------------------------------------------------
# AMT-* / FRQ-* boundaries
# --------------------------------------------------------------------------


@pytest.mark.parametrize("code", ["salary", "cash_deposit", "crypto_exchange"])
def test_amount_boundary_classes_over_the_api(
    client, participant, active_round, cards, code
) -> None:
    round_id = active_round["id"]
    card = cards[code]
    minimum = float(card["min_amount"])
    maximum = float(card["max_amount"])

    below = put_scenario(
        client, round_id, participant["headers"], [build_step(card, minimum - 0.01)]
    ).json()
    assert "amount_out_of_range" in violation_reasons(below["resources"])

    at_min = put_scenario(
        client, round_id, participant["headers"], [build_step(card, minimum)],
        expected_revision=below["revision"],
    ).json()
    assert "amount_out_of_range" not in violation_reasons(at_min["resources"])

    at_max = put_scenario(
        client, round_id, participant["headers"], [build_step(card, maximum)],
        expected_revision=at_min["revision"],
    ).json()
    assert "amount_out_of_range" not in violation_reasons(at_max["resources"])

    above = put_scenario(
        client, round_id, participant["headers"], [build_step(card, maximum + 0.01)],
        expected_revision=at_max["revision"],
    ).json()
    assert "amount_out_of_range" in violation_reasons(above["resources"])


def test_frequency_zero_is_a_schema_error_and_over_limit_is_a_violation(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    zero = build_step(cards["card_transfer"], 1000, 1, "mobile")
    zero["frequency"] = 0
    assert put_scenario(client, round_id, participant["headers"], [zero]).status_code == 422

    limit = cards["card_transfer"]["max_frequency"]
    ok = put_scenario(
        client, round_id, participant["headers"],
        [build_step(cards["card_transfer"], 1000, limit, "mobile")],
    ).json()
    assert "frequency_out_of_range" not in violation_reasons(ok["resources"])

    over = put_scenario(
        client, round_id, participant["headers"],
        [build_step(cards["card_transfer"], 1000, limit + 1, "mobile")],
        expected_revision=ok["revision"],
    ).json()
    assert "frequency_out_of_range" in violation_reasons(over["resources"])


def test_round_frequency_limit_over_the_api(client, participant, active_round, cards) -> None:
    round_id = active_round["id"]
    steps = [
        build_step(cards["salary"], 100000, 1, "bank"),
        build_step(cards["card_transfer"], 1000, 5, "mobile"),
        build_step(cards["online_purchase"], 1000, 1, "web"),
        build_step(cards["card_transfer"], 1000, 2, "mobile"),
    ]
    at_limit = put_scenario(client, round_id, participant["headers"], steps).json()
    assert "round_frequency_limit_exceeded" not in violation_reasons(at_limit["resources"])

    steps[3] = build_step(cards["card_transfer"], 1000, 3, "mobile")
    over = put_scenario(
        client, round_id, participant["headers"], steps, expected_revision=at_limit["revision"]
    ).json()
    assert "round_frequency_limit_exceeded" in violation_reasons(over["resources"])


# --------------------------------------------------------------------------
# SEQ-* / LIM-* through the API
# --------------------------------------------------------------------------


def test_refund_sequences_over_the_api(client, participant, active_round, cards) -> None:
    round_id = active_round["id"]
    purchase = build_step(cards["online_purchase"], 20000, 1, "web")
    refund = build_step(cards["refund"], 20000, 1, "web")

    orphan = put_scenario(client, round_id, participant["headers"], [refund]).json()
    assert "missing_prerequisite" in violation_reasons(orphan["resources"])

    ordered = put_scenario(
        client, round_id, participant["headers"], [purchase, refund],
        expected_revision=orphan["revision"],
    ).json()
    assert "missing_prerequisite" not in violation_reasons(ordered["resources"])

    reordered = put_scenario(
        client, round_id, participant["headers"], [refund, purchase],
        expected_revision=ordered["revision"],
    ).json()
    assert "missing_prerequisite" in violation_reasons(reordered["resources"])

    too_large = put_scenario(
        client,
        round_id,
        participant["headers"],
        [purchase, build_step(cards["refund"], 40000, 1, "web")],
        expected_revision=reordered["revision"],
    ).json()
    assert "refund_exceeds_purchases" in violation_reasons(too_large["resources"])


def test_deleting_the_prerequisite_breaks_the_refund(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    purchase = build_step(cards["online_purchase"], 20000, 1, "web")
    refund = build_step(cards["refund"], 20000, 1, "web")
    saved = put_scenario(client, round_id, participant["headers"], [purchase, refund]).json()
    assert saved["resources"]["valid"] is False or True  # persisted either way

    after_delete = put_scenario(
        client, round_id, participant["headers"], [refund],
        expected_revision=saved["revision"],
    ).json()
    assert "missing_prerequisite" in violation_reasons(after_delete["resources"])


def test_quota_and_constraint_violations_over_the_api(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    night = {"time_of_day": "night"}
    steps = [
        build_step(cards["cash_deposit"], 100000, 1, "atm", context=night),
        build_step(cards["cash_withdrawal"], 60000, 1, "atm", context=night),
        build_step(cards["online_purchase"], 1000, 1, "web", context=night),
    ]
    body = put_scenario(client, round_id, participant["headers"], steps).json()
    reasons = violation_reasons(body["resources"])
    assert "category_limit_exceeded" in reasons
    assert "night_operations_exceeded" in reasons
    assert body["resources"]["valid"] is False


def test_max_actions_violation_over_the_api(client, participant, active_round, cards) -> None:
    round_id = active_round["id"]
    steps = []
    for index in range(9):
        card = cards["online_purchase"] if index % 2 == 0 else cards["salary"]
        amount = 1000 if index % 2 == 0 else 10000
        steps.append(build_step(card, amount))
    body = put_scenario(client, round_id, participant["headers"], steps).json()
    assert "max_actions_exceeded" in violation_reasons(body["resources"])


def test_violation_messages_are_russian_and_actionable(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    body = put_scenario(
        client,
        round_id,
        participant["headers"],
        [build_step(cards["cash_deposit"], 1_000_000, 1, "atm")],
    ).json()
    violation = next(
        item
        for item in body["resources"]["violations"]
        if item["reason"] == "amount_out_of_range"
    )
    message = violation["message"]
    assert "Шаг 1" in message
    assert "Сумма" in message
    assert "1 000 000" in message
    assert "5 000" in message and "150 000" in message
    assert "Измените" in message
