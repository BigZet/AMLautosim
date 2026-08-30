"""Draft lifecycle: revisions, mutation ids, structural vs business failures."""

from __future__ import annotations

import json
import uuid

import psycopg2

from tests.helpers import build_step, error_reasons, put_scenario, valid_chain, violation_reasons


def test_scenario_is_null_before_the_first_put(client, participant, active_round) -> None:
    response = client.get(
        f"/api/v1/rounds/{active_round['id']}/scenario", headers=participant["headers"]
    )
    assert response.status_code == 200
    assert response.json() is None


def test_empty_draft_can_be_saved(client, participant, active_round) -> None:
    response = put_scenario(client, active_round["id"], participant["headers"], [])
    assert response.status_code == 200
    body = response.json()
    assert body["revision"] == 1
    assert body["steps"] == []
    assert body["resources"]["valid"] is True


def test_first_put_creates_revision_one_and_material_edits_increment(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    chain = valid_chain(cards)
    first = put_scenario(client, round_id, participant["headers"], chain)
    assert first.status_code == 200
    assert first.json()["revision"] == 1

    changed = [*chain]
    changed[2] = build_step(cards["card_transfer"], 61000, 1, "mobile")
    second = put_scenario(client, round_id, participant["headers"], changed, expected_revision=1)
    assert second.json()["revision"] == 2


def test_identical_put_does_not_grow_the_revision(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    chain = valid_chain(cards)
    first = put_scenario(client, round_id, participant["headers"], chain)
    again = put_scenario(client, round_id, participant["headers"], chain, expected_revision=1)
    assert again.status_code == 200
    assert again.json()["revision"] == first.json()["revision"] == 1


def test_retry_with_the_same_mutation_id_and_payload_returns_the_first_result(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    chain = valid_chain(cards)
    mutation = str(uuid.uuid4())
    first = put_scenario(
        client, round_id, participant["headers"], chain, mutation_id=mutation
    )
    # The client never saw the response, so it retries with the *stale* revision.
    retry = put_scenario(
        client, round_id, participant["headers"], chain, expected_revision=0, mutation_id=mutation
    )
    assert retry.status_code == 200
    assert retry.json()["revision"] == first.json()["revision"]


def test_same_mutation_id_with_a_different_payload_conflicts(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    mutation = str(uuid.uuid4())
    put_scenario(
        client, round_id, participant["headers"], valid_chain(cards), mutation_id=mutation
    )
    other = [build_step(cards["salary"], 50000, 1, "bank")]
    response = put_scenario(
        client, round_id, participant["headers"], other, expected_revision=1, mutation_id=mutation
    )
    assert response.status_code == 409
    assert response.json()["code"] == "mutation_id_reused"


def test_stale_revision_from_a_second_window_conflicts(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    put_scenario(client, round_id, participant["headers"], valid_chain(cards))
    stale = put_scenario(
        client,
        round_id,
        participant["headers"],
        [build_step(cards["salary"], 50000, 1, "bank")],
        expected_revision=0,
    )
    assert stale.status_code == 409
    body = stale.json()
    assert body["code"] == "scenario_revision_conflict"
    assert body["details"]["current_revision"] == 1


def test_business_invalid_draft_is_persisted_with_valid_false(
    client, participant, active_round, cards, db_dsn
) -> None:
    round_id = active_round["id"]
    steps = [build_step(cards["card_transfer"], 500000, 1, "mobile")]
    response = put_scenario(client, round_id, participant["headers"], steps)
    assert response.status_code == 200
    body = response.json()
    assert body["resources"]["valid"] is False
    assert "insufficient_balance" in violation_reasons(body["resources"])

    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, revision, resource_snapshot FROM scenarios WHERE id = %s",
                (body["id"],),
            )
            status, revision, snapshot = cursor.fetchone()
    finally:
        connection.close()
    assert status == "draft"
    assert revision == 1
    stored = snapshot if isinstance(snapshot, dict) else json.loads(snapshot)
    assert stored["valid"] is False


def test_business_invalid_draft_cannot_be_submitted(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    steps = [build_step(cards["card_transfer"], 500000, 1, "mobile")]
    saved = put_scenario(client, round_id, participant["headers"], steps).json()
    response = client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": saved["revision"]},
        headers=participant["headers"],
    )
    assert response.status_code == 400
    assert response.json()["code"] == "scenario_validation_failed"
    assert "insufficient_balance" in error_reasons(response)


def test_structurally_invalid_payload_does_not_touch_the_stored_draft(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    good = put_scenario(client, round_id, participant["headers"], valid_chain(cards)).json()

    bad = put_scenario(
        client,
        round_id,
        participant["headers"],
        [build_step(cards["salary"], 50000, 1, "atm")],
        expected_revision=good["revision"],
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "validation_error"
    assert "channel_not_allowed" in error_reasons(bad)

    current = client.get(
        f"/api/v1/rounds/{round_id}/scenario", headers=participant["headers"]
    ).json()
    assert current["revision"] == good["revision"]
    assert current["steps"] == good["steps"]


def test_unknown_channel_is_rejected_by_the_schema(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    step = build_step(cards["salary"], 50000, 1, "bank")
    step["context"]["channel"] = "carrier_pigeon"
    response = put_scenario(client, round_id, participant["headers"], [step])
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_extra_field_in_the_payload_is_rejected(client, participant, active_round, cards) -> None:
    round_id = active_round["id"]
    step = build_step(cards["salary"], 50000, 1, "bank")
    step["card_code"] = "salary"
    response = put_scenario(client, round_id, participant["headers"], [step])
    assert response.status_code == 422


def test_channel_is_stored_once_and_survives_a_round_trip(
    client, participant, active_round, cards, db_dsn
) -> None:
    round_id = active_round["id"]
    steps = [build_step(cards["card_transfer"], 5000, 1, "branch")]
    saved = put_scenario(client, round_id, participant["headers"], steps).json()

    stored_step = saved["steps"][0]
    assert stored_step["context"]["channel"] == "branch"
    assert "channel" not in {key for key in stored_step if key != "context"}

    fetched = client.get(
        f"/api/v1/rounds/{round_id}/scenario", headers=participant["headers"]
    ).json()
    assert fetched["steps"][0]["context"]["channel"] == "branch"

    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT steps FROM scenarios WHERE id = %s", (saved["id"],))
            raw = cursor.fetchone()[0]
    finally:
        connection.close()
    rows = raw if isinstance(raw, list) else json.loads(raw)
    assert rows[0]["context"]["channel"] == "branch"


def test_step_ids_are_stable_across_edit_and_reorder(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    chain = valid_chain(cards)
    ids = [step["step_id"] for step in chain]
    put_scenario(client, round_id, participant["headers"], chain)

    edited = [dict(step) for step in chain]
    edited[1]["amount"] = "110000.00"
    response = put_scenario(
        client, round_id, participant["headers"], edited, expected_revision=1
    )
    assert [step["step_id"] for step in response.json()["steps"]] == ids

    reordered = [edited[2], edited[0], edited[1]]
    response = put_scenario(
        client, round_id, participant["headers"], reordered, expected_revision=2
    )
    assert [step["step_id"] for step in response.json()["steps"]] == [
        ids[2],
        ids[0],
        ids[1],
    ]


def test_duplicating_a_step_requires_a_new_step_id(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    original = build_step(cards["card_transfer"], 20000, 1, "web")
    duplicate_same_id = [original, dict(original)]
    response = put_scenario(client, round_id, participant["headers"], duplicate_same_id)
    assert response.status_code == 422
    assert "duplicate_step_id" in error_reasons(response)

    duplicate_new_id = [original, {**original, "step_id": str(uuid.uuid4())}]
    ok = put_scenario(client, round_id, participant["headers"], duplicate_new_id)
    assert ok.status_code == 200
    assert len({step["step_id"] for step in ok.json()["steps"]}) == 2


def test_submit_flow_and_idempotency(client, participant, active_round, cards) -> None:
    round_id = active_round["id"]
    saved = put_scenario(client, round_id, participant["headers"], valid_chain(cards)).json()
    assert saved["resources"]["objective"]["reached"] is True

    submitted = client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": saved["revision"]},
        headers=participant["headers"],
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["submitted_at"] is not None

    repeat = client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": saved["revision"]},
        headers=participant["headers"],
    )
    assert repeat.status_code == 200
    assert repeat.json()["submitted_at"] == submitted.json()["submitted_at"]


def test_submit_with_a_stale_revision_conflicts(client, participant, active_round, cards) -> None:
    round_id = active_round["id"]
    saved = put_scenario(client, round_id, participant["headers"], valid_chain(cards)).json()
    response = client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": saved["revision"] + 5},
        headers=participant["headers"],
    )
    assert response.status_code == 409
    assert response.json()["code"] == "scenario_revision_conflict"


def test_editing_a_submitted_scenario_returns_it_to_draft(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    chain = valid_chain(cards)
    saved = put_scenario(client, round_id, participant["headers"], chain).json()
    client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": saved["revision"]},
        headers=participant["headers"],
    )

    edited = [dict(step) for step in chain]
    edited[2]["amount"] = "70000.00"
    response = put_scenario(
        client, round_id, participant["headers"], edited, expected_revision=saved["revision"]
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "draft"
    assert body["submitted_at"] is None
    assert body["revision"] == saved["revision"] + 1

    resubmitted = client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": body["revision"]},
        headers=participant["headers"],
    )
    assert resubmitted.status_code == 200
    assert resubmitted.json()["status"] == "submitted"


def test_submitting_an_empty_scenario_is_blocked(client, participant, active_round) -> None:
    round_id = active_round["id"]
    saved = put_scenario(client, round_id, participant["headers"], []).json()
    response = client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": saved["revision"]},
        headers=participant["headers"],
    )
    assert response.status_code == 400
    assert "scenario_empty" in error_reasons(response)


def test_scenario_survives_a_new_api_instance(client, participant, active_round, cards) -> None:
    """The canonical chain lives in PostgreSQL, not in process memory."""
    round_id = active_round["id"]
    saved = put_scenario(client, round_id, participant["headers"], valid_chain(cards)).json()

    from fastapi.testclient import TestClient

    from aml_workshop_simulator.api.main import app

    with TestClient(app) as fresh_client:
        response = fresh_client.get(
            f"/api/v1/rounds/{round_id}/scenario", headers=participant["headers"]
        )
    assert response.status_code == 200
    assert response.json()["revision"] == saved["revision"]
    assert response.json()["steps"] == saved["steps"]
