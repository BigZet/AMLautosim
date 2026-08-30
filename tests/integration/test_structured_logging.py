"""Structured logging as `docs/operations.md` §7-8 defines it.

Two things are checked here that reading the code cannot settle: that the lines
are actually well-formed JSON carrying the mandatory fields, and that nothing
from the §7 denylist reaches them. The second is the one that matters — a log
stream is not access-controlled the way the audit table is, and every router
logs, so the guarantee has to be tested rather than reviewed.
"""

from __future__ import annotations

import json
import logging
import uuid

import pytest

from aml_workshop_simulator.core.logging import (
    ALLOWED_FIELDS,
    LOGGER_NAME,
    JsonFormatter,
)
from tests.conftest import PARTICIPANT_PASSWORD, register_participant
from tests.helpers import put_scenario, valid_chain

#: §7 names these explicitly as values that must never be logged.
FORBIDDEN_KEYS = {
    "email",
    "display_name",
    "password",
    "hashed_password",
    "session_id",
    "session_id_hash",
    "x-session-id",
    "cookie",
    "authorization",
    "steps",
    "action_details",
    "explanation",
    "dsn",
    "database_url",
    "idempotency_key",
}

MANDATORY_KEYS = {"timestamp", "level", "service", "event", "request_id"}


class _Collector(logging.Handler):
    """Keeps every record it is given, so the test can render them itself."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture()
def captured():
    """Every `aml` record emitted during the test, rendered as its JSON line.

    A handler of our own rather than pytest's `caplog`: production sets
    `propagate = False`, so nothing reaches the root logger, and pytest swaps
    its capture handler between the setup and call phases — a handler attached
    from a fixture stops being the one `caplog.records` reads.
    """
    # Importing the app is what runs `configure_logging`, and that call replaces
    # the logger's handlers — including this one, if it were attached first.
    import aml_workshop_simulator.api.main  # noqa: F401

    logger = logging.getLogger(LOGGER_NAME)
    formatter = JsonFormatter("api")
    collector = _Collector()
    logger.addHandler(collector)

    def lines() -> list[dict]:
        return [json.loads(formatter.format(record)) for record in collector.records]

    try:
        yield lines
    finally:
        logger.removeHandler(collector)


def test_every_line_is_json_with_the_documented_fields(client, captured):
    client.get("/api/v1/rounds/current")

    lines = captured()
    assert lines, "the API logged nothing at all"
    for line in lines:
        assert set(line) >= MANDATORY_KEYS, line
        assert line["service"] == "api"
    events = [line["event"] for line in lines]
    assert "request_started" in events
    assert "request_completed" in events

    completed = next(line for line in lines if line["event"] == "request_completed")
    assert completed["status_code"] == 200
    assert completed["route"] == "/api/v1/rounds/current"
    assert isinstance(completed["latency_ms"], (int, float))


def test_the_response_header_is_the_key_to_the_log(client, captured):
    """§8: an operator finds an incident by request id, then follows the chain."""
    correlation = str(uuid.uuid4())

    response = client.get(
        "/api/v1/rounds/current", headers={"X-Request-ID": correlation}
    )
    assert response.headers["X-Request-ID"] == correlation

    ids = {line["request_id"] for line in captured()}
    assert ids == {correlation}, "the chain is not correlated end to end"


def test_a_full_round_never_logs_anything_from_the_denylist(
    client, admin_headers, participant, active_round, cards, captured
):
    """The path that touches the most personal data at once."""
    round_id = active_round["id"]
    saved = put_scenario(
        client, round_id, participant["headers"], valid_chain(cards), expected_revision=0
    )
    assert saved.status_code == 200, saved.text
    client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": saved.json()["revision"]},
        headers=participant["headers"],
    )
    client.post(
        f"/api/v1/admin/rounds/{round_id}/score",
        headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
    )

    lines = captured()
    # Guard against a vacuous pass: an empty log contains no secrets either.
    assert {"scenario_saved", "scenario_submitted", "round_scored"} <= {
        line["event"] for line in lines
    }, sorted({line["event"] for line in lines})

    blob = json.dumps(lines, ensure_ascii=False)
    assert participant["email"] not in blob
    assert participant["display_name"] not in blob
    assert participant["session_id"] not in blob
    assert PARTICIPANT_PASSWORD not in blob
    for key in FORBIDDEN_KEYS:
        assert f'"{key}"' not in blob, f"{key} reached the log"


def test_a_failed_login_is_logged_without_the_address(client, captured):
    """§7: auth failure is an event; the email is not part of it."""
    email = "ghost@example.com"
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong-password-here", "audience": "play"},
    )
    assert response.status_code == 401

    lines = captured()
    assert any(line["event"] == "login_failed" for line in lines)
    assert email not in json.dumps(lines, ensure_ascii=False)


def test_a_successful_login_carries_the_role_and_not_the_person(client, captured):
    player = register_participant(client)

    lines = [line for line in captured() if line["event"] == "login_succeeded"]
    assert lines, "a successful login was not logged"
    assert lines[-1]["user_id"] == player["id"]
    assert lines[-1]["role"] == "participant"
    assert player["display_name"] not in json.dumps(lines, ensure_ascii=False)


def test_a_refusal_is_logged_with_its_code(
    client, participant, active_round, cards, captured
):
    """§7 asks for scenario conflicts by name."""
    round_id = active_round["id"]
    put_scenario(
        client, round_id, participant["headers"], valid_chain(cards), expected_revision=0
    )
    stale = put_scenario(
        client, round_id, participant["headers"], valid_chain(cards), expected_revision=0
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "scenario_revision_conflict"

    refusals = [line for line in captured() if line["event"] == "request_refused"]
    assert [line["reason_code"] for line in refusals] == [
        "scenario_revision_conflict"
    ]
    assert refusals[0]["status_code"] == 409
    assert refusals[0]["level"] == "WARNING"


def test_a_field_outside_the_allowlist_is_dropped_not_logged(captured):
    """The allowlist is the guarantee; a careless call site must not break it."""
    from aml_workshop_simulator.core.logging import log_event

    log_event("test_event", user_id=7, email="secret@example.com")

    line = next(item for item in captured() if item["event"] == "test_event")
    assert line["user_id"] == 7
    assert "email" not in line
    assert "secret@example.com" not in json.dumps(line)
    # The name is reported so the mistake is visible; the value never is.
    assert line["dropped_fields"] == ["email"]


def test_the_allowlist_excludes_every_documented_secret():
    assert not (ALLOWED_FIELDS & FORBIDDEN_KEYS)
