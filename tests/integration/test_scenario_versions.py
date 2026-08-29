"""Saved draft history and the live preview, over the real HTTP API.

Every explicit save appends an immutable version; restoring an old one appends
a copy of it instead of deleting anything newer; submitting freezes exactly one
version and scoring reads only that one. The preview endpoint returns the very
snapshot a save would store, which is what lets the participant UI show live
resources without persisting anything.
"""

from __future__ import annotations

import uuid

import psycopg2

from tests.helpers import build_step, put_scenario, valid_chain


def versions(client, round_id: int, headers: dict[str, str]) -> list[dict]:
    response = client.get(
        f"/api/v1/rounds/{round_id}/scenario/versions", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["rows"]


def preview(client, round_id: int, headers: dict[str, str], steps: list[dict]) -> dict:
    response = client.post(
        f"/api/v1/rounds/{round_id}/scenario/preview",
        json={"steps": steps},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------
# Preview
# --------------------------------------------------------------------------


def test_preview_matches_the_snapshot_a_save_would_store(
    client, participant, active_round, cards
) -> None:
    """Parity: the local preview and the stored snapshot are the same object."""
    round_id = active_round["id"]
    chain = valid_chain(cards)

    previewed = preview(client, round_id, participant["headers"], chain)
    saved = put_scenario(client, round_id, participant["headers"], chain).json()

    assert previewed["resources"] == saved["resources"]
    assert previewed["blockers"] == []


def test_preview_persists_nothing(client, participant, active_round, cards) -> None:
    round_id = active_round["id"]
    preview(client, round_id, participant["headers"], valid_chain(cards))
    assert (
        client.get(
            f"/api/v1/rounds/{round_id}/scenario", headers=participant["headers"]
        ).json()
        is None
    )
    assert versions(client, round_id, participant["headers"]) == []


def test_preview_reports_business_violations_without_saving(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    body = preview(
        client,
        round_id,
        participant["headers"],
        [build_step(cards["card_transfer"], 400000, 1, "mobile")],
    )
    reasons = [item["reason"] for item in body["resources"]["violations"]]
    assert "insufficient_balance" in reasons
    assert body["resources"]["valid"] is False
    assert any(item["reason"] == "insufficient_balance" for item in body["blockers"])


def test_preview_rejects_a_structurally_invalid_chain(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    step = build_step(cards["salary"], 50000, 1, "atm")
    response = client.post(
        f"/api/v1/rounds/{round_id}/scenario/preview",
        json={"steps": [step]},
        headers=participant["headers"],
    )
    assert response.status_code == 422
    reasons = [
        item["reason"] for item in response.json()["details"]["violations"]
    ]
    assert "channel_not_allowed" in reasons


def test_preview_reflects_every_kind_of_chain_edit(
    client, participant, active_round, cards
) -> None:
    """Add, edit, reorder, delete and clear each produce their own snapshot."""
    round_id = active_round["id"]
    headers = participant["headers"]
    salary = build_step(cards["salary"], 100000, 1, "bank")
    transfer = build_step(cards["card_transfer"], 40000, 1, "mobile")

    added = preview(client, round_id, headers, [salary])["resources"]
    assert added["resources_after"]["balance"] == "350000.00"

    grown = preview(client, round_id, headers, [salary, transfer])["resources"]
    assert grown["resources_after"]["balance"] == "309800.00"
    assert grown["limit_usage"]["actions"] == 2

    reordered = preview(client, round_id, headers, [transfer, salary])["resources"]
    assert reordered["totals"] == grown["totals"]
    assert reordered["per_step"][0]["card_code"] == "card_transfer"

    edited = preview(
        client,
        round_id,
        headers,
        [salary, {**transfer, "amount": "10000.00"}],
    )["resources"]
    assert edited["resources_after"]["balance"] == "339950.00"

    deleted = preview(client, round_id, headers, [salary])["resources"]
    assert deleted == added

    cleared = preview(client, round_id, headers, [])["resources"]
    assert cleared["resources_after"]["balance"] == "250000.00"
    assert cleared["limit_usage"]["actions"] == 0


def test_preview_requires_a_participant_session(client, active_round, cards) -> None:
    response = client.post(
        f"/api/v1/rounds/{active_round['id']}/scenario/preview", json={"steps": []}
    )
    assert response.status_code == 401


# --------------------------------------------------------------------------
# Version history
# --------------------------------------------------------------------------


def test_every_explicit_save_appends_a_version(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    headers = participant["headers"]

    first = put_scenario(
        client, round_id, headers, [build_step(cards["salary"], 100000, 1, "bank")]
    ).json()
    second = put_scenario(
        client,
        round_id,
        headers,
        [
            build_step(cards["salary"], 100000, 1, "bank"),
            build_step(cards["card_transfer"], 50000, 1, "mobile"),
        ],
        expected_revision=first["revision"],
    ).json()

    rows = versions(client, round_id, headers)
    assert [row["revision"] for row in rows] == [2, 1]
    assert rows[0]["is_current"] is True
    assert rows[1]["is_current"] is False
    assert rows[0]["step_count"] == 2
    assert rows[1]["step_count"] == 1
    assert second["version_count"] == 2
    assert rows[0]["balance_after"] == "299750.00"


def test_a_version_can_be_named(client, participant, active_round, cards) -> None:
    round_id = active_round["id"]
    response = client.put(
        f"/api/v1/rounds/{round_id}/scenario",
        json={
            "expected_revision": 0,
            "client_mutation_id": str(uuid.uuid4()),
            "steps": valid_chain(cards),
            "label": "Осторожный вариант",
        },
        headers=participant["headers"],
    )
    assert response.status_code == 200, response.text
    assert versions(client, round_id, participant["headers"])[0]["label"] == (
        "Осторожный вариант"
    )


def test_an_unchanged_save_does_not_append_a_version(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    headers = participant["headers"]
    chain = valid_chain(cards)
    first = put_scenario(client, round_id, headers, chain).json()
    again = put_scenario(client, round_id, headers, chain, first["revision"]).json()
    assert again["revision"] == first["revision"]
    assert len(versions(client, round_id, headers)) == 1


def test_a_stored_version_carries_its_full_chain_and_snapshot(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    put_scenario(client, round_id, participant["headers"], valid_chain(cards))
    response = client.get(
        f"/api/v1/rounds/{round_id}/scenario/versions/1", headers=participant["headers"]
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["steps"]) == 3
    assert body["resources"]["valid"] is True
    assert body["resources"]["per_step"][0]["resources_before"]["balance"] == "250000.00"


def test_restoring_an_old_version_keeps_the_newer_ones(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    headers = participant["headers"]
    one_step = [build_step(cards["salary"], 100000, 1, "bank")]
    two_steps = [*one_step, build_step(cards["card_transfer"], 50000, 1, "mobile")]

    first = put_scenario(client, round_id, headers, one_step).json()
    second = put_scenario(client, round_id, headers, two_steps, first["revision"]).json()

    restored = client.post(
        f"/api/v1/rounds/{round_id}/scenario/versions/1/restore",
        json={
            "expected_revision": second["revision"],
            "client_mutation_id": str(uuid.uuid4()),
        },
        headers=headers,
    )
    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert body["revision"] == 3
    assert len(body["steps"]) == 1

    rows = versions(client, round_id, headers)
    assert [row["revision"] for row in rows] == [3, 2, 1]
    assert rows[0]["restored_from_revision"] == 1
    assert rows[0]["is_current"] is True
    # The version that was replaced is still readable, untouched.
    assert (
        client.get(
            f"/api/v1/rounds/{round_id}/scenario/versions/2", headers=headers
        ).json()["step_count"]
        == 2
    )


def test_restoring_and_submitting_reach_the_audit_trail(
    client, participant, active_round, cards, admin_headers
) -> None:
    """The organiser can tell who rolled back and who submitted, and when."""
    round_id = active_round["id"]
    headers = participant["headers"]
    first = put_scenario(client, round_id, headers, valid_chain(cards)).json()
    second = put_scenario(
        client,
        round_id,
        headers,
        [*valid_chain(cards), build_step(cards["cash_deposit"], 20000, 1, "atm")],
        first["revision"],
    ).json()
    restored = client.post(
        f"/api/v1/rounds/{round_id}/scenario/versions/1/restore",
        json={
            "expected_revision": second["revision"],
            "client_mutation_id": str(uuid.uuid4()),
        },
        headers=headers,
    ).json()
    submitted = client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": restored["revision"]},
        headers=headers,
    )
    assert submitted.status_code == 200, submitted.text

    events = client.get(
        f"/api/v1/admin/rounds/{round_id}/audit-events", headers=admin_headers
    ).json()["rows"]
    by_type = {row["event_type"]: row for row in events}
    assert "scenario_version_restored" in by_type
    assert "scenario_submitted" in by_type

    restore_event = by_type["scenario_version_restored"]
    assert restore_event["actor_user_id"] == participant["id"]
    assert restore_event["round_id"] == round_id
    assert restore_event["metadata"]["restored_from_revision"] == 1

    submit_event = by_type["scenario_submitted"]
    assert submit_event["actor_user_id"] == participant["id"]
    assert submit_event["metadata"]["revision"] == restored["revision"]
    # The trail carries identifiers and counters, never the chain itself.
    assert "steps" not in submit_event["metadata"]


def test_restoring_refreshes_the_expected_revision(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    headers = participant["headers"]
    first = put_scenario(
        client, round_id, headers, [build_step(cards["salary"], 100000, 1, "bank")]
    ).json()
    put_scenario(client, round_id, headers, valid_chain(cards), first["revision"])

    stale = client.post(
        f"/api/v1/rounds/{round_id}/scenario/versions/1/restore",
        json={"expected_revision": 1, "client_mutation_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "scenario_revision_conflict"
    assert stale.json()["details"]["current_revision"] == 2


def test_restoring_is_idempotent_for_a_retried_command(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    headers = participant["headers"]
    first = put_scenario(
        client, round_id, headers, [build_step(cards["salary"], 100000, 1, "bank")]
    ).json()
    put_scenario(client, round_id, headers, valid_chain(cards), first["revision"])

    mutation = str(uuid.uuid4())
    body = {"expected_revision": 2, "client_mutation_id": mutation}
    first_call = client.post(
        f"/api/v1/rounds/{round_id}/scenario/versions/1/restore", json=body, headers=headers
    ).json()
    replay = client.post(
        f"/api/v1/rounds/{round_id}/scenario/versions/1/restore", json=body, headers=headers
    ).json()
    assert first_call["revision"] == replay["revision"] == 3
    assert len(versions(client, round_id, headers)) == 3


def test_restoring_an_unknown_version_is_a_404(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    saved = put_scenario(
        client, round_id, participant["headers"], valid_chain(cards)
    ).json()
    response = client.post(
        f"/api/v1/rounds/{round_id}/scenario/versions/99/restore",
        json={
            "expected_revision": saved["revision"],
            "client_mutation_id": str(uuid.uuid4()),
        },
        headers=participant["headers"],
    )
    assert response.status_code == 404
    assert response.json()["code"] == "scenario_version_not_found"


# --------------------------------------------------------------------------
# Submit pins one version
# --------------------------------------------------------------------------


def test_submitting_freezes_one_version_and_scoring_uses_it(
    client, admin_headers, participant, active_round, cards, db_dsn
) -> None:
    round_id = active_round["id"]
    headers = participant["headers"]

    weak = [build_step(cards["salary"], 100000, 1, "bank")]
    first = put_scenario(client, round_id, headers, weak).json()
    good = put_scenario(
        client, round_id, headers, valid_chain(cards), first["revision"]
    ).json()

    submitted = client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": good["revision"]},
        headers=headers,
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["submitted_revision"] == good["revision"]

    rows = versions(client, round_id, headers)
    assert [row["is_submitted"] for row in rows] == [True, False]

    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT v.revision FROM scenarios s "
                "JOIN scenario_versions v ON v.id = s.submitted_version_id"
            )
            assert cursor.fetchone()[0] == good["revision"]
    finally:
        connection.close()

    scored = client.post(
        f"/api/v1/admin/rounds/{round_id}/score",
        headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert scored.status_code == 200, scored.text
    result = client.get(f"/api/v1/rounds/{round_id}/result", headers=headers).json()
    assert len(result["resources"]["per_step"]) == 3


def test_editing_after_submit_reopens_the_draft_and_appends_a_version(
    client, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    headers = participant["headers"]
    saved = put_scenario(client, round_id, headers, valid_chain(cards)).json()
    client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": saved["revision"]},
        headers=headers,
    )

    changed = valid_chain(cards)
    changed[0]["amount"] = "130000.00"
    reopened = put_scenario(
        client, round_id, headers, changed, saved["revision"]
    ).json()
    assert reopened["status"] == "draft"
    assert reopened["submitted_revision"] is None
    rows = versions(client, round_id, headers)
    assert len(rows) == 2
    assert rows[0]["is_submitted"] is False


# --------------------------------------------------------------------------
# What the administrator sees
# --------------------------------------------------------------------------


def test_the_admin_sees_every_version_of_every_participant(
    client, admin_headers, participant, second_participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    first = put_scenario(
        client, round_id, participant["headers"], [build_step(cards["salary"], 100000, 1, "bank")]
    ).json()
    put_scenario(
        client, round_id, participant["headers"], valid_chain(cards), first["revision"]
    )
    put_scenario(client, round_id, second_participant["headers"], valid_chain(cards))

    detail = client.get(
        f"/api/v1/admin/rounds/{round_id}/participants/{participant['id']}",
        headers=admin_headers,
    ).json()
    assert [row["revision"] for row in detail["versions"]] == [2, 1]
    assert detail["scenario"]["version_count"] == 2

    other = client.get(
        f"/api/v1/admin/rounds/{round_id}/participants/{second_participant['id']}",
        headers=admin_headers,
    ).json()
    assert len(other["versions"]) == 1

    listing = client.get(
        f"/api/v1/admin/rounds/{round_id}/participants", headers=admin_headers
    ).json()
    counts = {row["id"]: row["version_count"] for row in listing["rows"]}
    assert counts[participant["id"]] == 2
    assert counts[second_participant["id"]] == 1


def test_the_admin_version_detail_shows_every_parameter_of_every_step(
    client, admin_headers, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    put_scenario(client, round_id, participant["headers"], valid_chain(cards))

    response = client.get(
        f"/api/v1/admin/rounds/{round_id}/participants/{participant['id']}"
        "/scenario-versions/1",
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["revision"] == 1
    assert len(body["described_steps"]) == 3

    step = body["described_steps"][0]
    assert step["card"]["code"] == "salary"
    assert step["card"]["title"] == "Получить зарплату"
    assert step["card"]["id"] == cards["salary"]["id"]
    assert step["step_id"]
    assert step["amount"] == "120000.00"
    assert step["frequency"] == 1

    parameters = {row["param"]: row for row in step["parameters"]}
    # The channel, every context field and every action detail are present,
    # including the ones that happen to hold their default value.
    assert parameters["channel"]["display"] == "Банковское зачисление"
    assert parameters["context.time_of_day"]["display"] == "День"
    assert parameters["context.has_documents"]["value"] is True
    assert parameters["context.has_documents"]["display"] == "Да"
    assert parameters["action.employer_profile"]["display"] == "Проверенный работодатель"
    assert parameters["action.income_basis"]["value"] == "payroll_registry"
    assert set(parameters) >= {
        "channel",
        "context.recipient_type",
        "context.time_of_day",
        "context.velocity",
        "context.has_documents",
        "action.employer_profile",
        "action.income_basis",
    }

    assert step["resources_before"]["balance"] == "250000.00"
    assert step["resources_after"]["balance"] == "370000.00"
    assert step["costs"]["energy"] == 1
    assert step["gross"] == "120000.00"
    # The raw payload is served too, so nothing can be lost on the way.
    assert body["steps"][0]["context"]["channel"] == "bank"


def test_a_false_or_zero_parameter_is_not_dropped(
    client, admin_headers, participant, full_round, full_cards
) -> None:
    """A legacy round exposes `has_documents`; `false` must survive the trip."""
    round_id = full_round["id"]
    step = build_step(
        full_cards["cash_deposit"], 20000, 1, "atm", context={"has_documents": False}
    )
    put_scenario(client, round_id, participant["headers"], [step])

    body = client.get(
        f"/api/v1/admin/rounds/{round_id}/participants/{participant['id']}"
        "/scenario-versions/1",
        headers=admin_headers,
    ).json()
    parameters = {
        row["param"]: row for row in body["described_steps"][0]["parameters"]
    }
    assert parameters["context.has_documents"]["value"] is False
    assert parameters["context.has_documents"]["display"] == "Нет"


def test_version_history_is_private_to_its_owner(
    client, participant, second_participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    put_scenario(client, round_id, participant["headers"], valid_chain(cards))

    assert versions(client, round_id, second_participant["headers"]) == []
    response = client.get(
        f"/api/v1/rounds/{round_id}/scenario/versions/1",
        headers=second_participant["headers"],
    )
    assert response.status_code == 404
    assert response.json()["code"] == "scenario_not_found"


def test_a_participant_cannot_read_the_admin_version_endpoint(
    client, participant, second_participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    put_scenario(client, round_id, participant["headers"], valid_chain(cards))
    response = client.get(
        f"/api/v1/admin/rounds/{round_id}/participants/{participant['id']}"
        "/scenario-versions/1",
        headers=second_participant["headers"],
    )
    assert response.status_code == 403
