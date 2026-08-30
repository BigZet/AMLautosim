"""Round lifecycle and reusable configurations, over the real HTTP API.

`draft → active → stopped → scoring → completed`, plus the restart that creates
a *new* round without destroying anything, and the presets an organiser
prepares before the workshop.
"""

from __future__ import annotations

import copy
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg2
import pytest

from tests.conftest import register_participant
from tests.helpers import put_scenario, valid_chain


def draft_round(client, admin_headers) -> dict:
    rounds = client.get("/api/v1/admin/rounds", headers=admin_headers).json()
    return next(item for item in rounds if item["status"] == "draft")


def idempotency(admin_headers: dict[str, str]) -> dict[str, str]:
    return {**admin_headers, "Idempotency-Key": str(uuid.uuid4())}


def audit_types(client, admin_headers, round_id: int) -> list[str]:
    page = client.get(
        f"/api/v1/admin/rounds/{round_id}/audit-events", headers=admin_headers
    ).json()
    return [row["event_type"] for row in page["rows"]]


# --------------------------------------------------------------------------
# Before the start
# --------------------------------------------------------------------------


def test_a_draft_round_is_not_playable(client, admin_headers, participant) -> None:
    """Everything a participant could do is refused until the organiser starts."""
    round_obj = draft_round(client, admin_headers)
    round_id = round_obj["id"]

    assert client.get("/api/v1/rounds/active").json() is None
    current = client.get("/api/v1/rounds/current").json()
    assert current["id"] == round_id
    assert current["status"] == "draft"

    response = put_scenario(client, round_id, participant["headers"], [])
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "round_locked"
    assert body["details"]["round_status"] == "draft"
    assert "еще не запущен" in body["message"]


def test_start_opens_the_round_and_is_idempotent(client, admin_headers) -> None:
    round_obj = draft_round(client, admin_headers)
    first = client.post(
        f"/api/v1/admin/rounds/{round_obj['id']}/start", headers=idempotency(admin_headers)
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "active"
    assert first.json()["game_config"]["config_version"].startswith("round-config-v4:")

    second = client.post(
        f"/api/v1/admin/rounds/{round_obj['id']}/start", headers=idempotency(admin_headers)
    )
    assert second.status_code == 200
    assert second.json()["activated_at"] == first.json()["activated_at"]


def test_the_configuration_is_frozen_once_the_round_runs(
    client, admin_headers, active_round
) -> None:
    config = copy.deepcopy(active_round["game_config"])
    config["objectives"]["max_actions"] = 3
    response = client.put(
        f"/api/v1/admin/rounds/{active_round['id']}",
        json={
            "expected_config_revision": active_round["config_revision"],
            "game_config": config,
        },
        headers=admin_headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "round_config_locked"


# --------------------------------------------------------------------------
# Stop
# --------------------------------------------------------------------------


def test_stop_requires_confirmation(client, admin_headers, active_round) -> None:
    response = client.post(
        f"/api/v1/admin/rounds/{active_round['id']}/stop",
        json={"confirm": False},
        headers=idempotency(admin_headers),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "confirmation_required"
    still = client.get(
        f"/api/v1/admin/rounds/{active_round['id']}", headers=admin_headers
    ).json()
    assert still["status"] == "active"


def test_stop_blocks_every_participant_write_but_keeps_the_data(
    client, admin_headers, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    saved = put_scenario(client, round_id, participant["headers"], valid_chain(cards))
    assert saved.status_code == 200, saved.text
    revision = saved.json()["revision"]

    stopped = client.post(
        f"/api/v1/admin/rounds/{round_id}/stop",
        json={"confirm": True, "reason": "Время вышло"},
        headers=idempotency(admin_headers),
    )
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["status"] == "stopped"
    assert stopped.json()["stopped_at"] is not None

    write = put_scenario(
        client, round_id, participant["headers"], valid_chain(cards), revision
    )
    assert write.status_code == 409
    assert write.json()["code"] == "round_locked"
    assert "остановлен" in write.json()["message"]

    submit = client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": revision},
        headers=participant["headers"],
    )
    assert submit.status_code == 409

    # Nothing was thrown away: the draft is still readable.
    stored = client.get(
        f"/api/v1/rounds/{round_id}/scenario", headers=participant["headers"]
    ).json()
    assert stored["revision"] == revision
    assert len(stored["steps"]) == 3
    assert "round_stopped" in audit_types(client, admin_headers, round_id)


def test_a_stopped_round_can_still_be_scored(
    client, admin_headers, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    saved = put_scenario(client, round_id, participant["headers"], valid_chain(cards)).json()
    client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": saved["revision"]},
        headers=participant["headers"],
    )
    client.post(
        f"/api/v1/admin/rounds/{round_id}/stop",
        json={"confirm": True},
        headers=idempotency(admin_headers),
    )

    plan = client.get(
        f"/api/v1/admin/rounds/{round_id}/scoring-plan", headers=admin_headers
    ).json()
    assert plan["can_score"] is True
    assert plan["submitted_count"] == 1
    assert plan["excluded_draft_count"] == 0

    scored = client.post(
        f"/api/v1/admin/rounds/{round_id}/score", headers=idempotency(admin_headers)
    )
    assert scored.status_code == 200, scored.text
    assert scored.json()["scored_count"] == 1


def test_the_scoring_plan_counts_drafts_that_will_be_excluded(
    client, admin_headers, participant, second_participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    submitted = put_scenario(
        client, round_id, participant["headers"], valid_chain(cards)
    ).json()
    client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": submitted["revision"]},
        headers=participant["headers"],
    )
    put_scenario(client, round_id, second_participant["headers"], valid_chain(cards))

    plan = client.get(
        f"/api/v1/admin/rounds/{round_id}/scoring-plan", headers=admin_headers
    ).json()
    assert plan["submitted_count"] == 1
    assert plan["excluded_draft_count"] == 1
    assert plan["can_score"] is True


# --------------------------------------------------------------------------
# Restart
# --------------------------------------------------------------------------


def test_restart_creates_a_new_round_and_keeps_all_history(
    client, admin_headers, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    saved = put_scenario(client, round_id, participant["headers"], valid_chain(cards)).json()
    client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": saved["revision"]},
        headers=participant["headers"],
    )

    response = client.post(
        f"/api/v1/admin/rounds/{round_id}/restart",
        json={"confirm": True, "reason": "Повтор для второй группы"},
        headers=idempotency(admin_headers),
    )
    assert response.status_code == 201, response.text
    replacement = response.json()
    assert replacement["id"] != round_id
    assert replacement["status"] == "draft"
    assert replacement["restarted_from_round_id"] == round_id
    assert replacement["game_config"]["operations"] == (
        active_round["game_config"]["operations"]
    )

    previous = client.get(
        f"/api/v1/admin/rounds/{round_id}", headers=admin_headers
    ).json()
    assert previous["status"] == "stopped"

    # The old scenario, its versions and the audit trail are untouched.
    detail = client.get(
        f"/api/v1/admin/rounds/{round_id}/participants/{participant['id']}",
        headers=admin_headers,
    ).json()
    assert detail["scenario"]["status"] == "submitted"
    assert detail["versions"]
    assert "round_restarted" in audit_types(client, admin_headers, replacement["id"])


def test_restart_requires_confirmation(client, admin_headers, active_round) -> None:
    response = client.post(
        f"/api/v1/admin/rounds/{active_round['id']}/restart",
        json={"confirm": False},
        headers=idempotency(admin_headers),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "confirmation_required"


def test_a_double_restart_click_creates_only_one_round(
    client, admin_headers, active_round
) -> None:
    round_id = active_round["id"]
    first = client.post(
        f"/api/v1/admin/rounds/{round_id}/restart",
        json={"confirm": True},
        headers=idempotency(admin_headers),
    ).json()
    second = client.post(
        f"/api/v1/admin/rounds/{round_id}/restart",
        json={"confirm": True},
        headers=idempotency(admin_headers),
    ).json()
    assert first["id"] == second["id"]

    rounds = client.get("/api/v1/admin/rounds", headers=admin_headers).json()
    replacements = [
        item for item in rounds if item.get("restarted_from_round_id") == round_id
    ]
    assert len(replacements) == 1


def test_restart_can_start_the_replacement_immediately(
    client, admin_headers, active_round
) -> None:
    response = client.post(
        f"/api/v1/admin/rounds/{active_round['id']}/restart",
        json={"confirm": True, "activate": True, "title": "Второй заход"},
        headers=idempotency(admin_headers),
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "active"
    assert response.json()["title"] == "Второй заход"
    assert client.get("/api/v1/rounds/active").json()["id"] == response.json()["id"]


def test_two_concurrent_starts_leave_exactly_one_active_round(
    client, admin_headers, db_dsn
) -> None:
    """Two administrators pressing «Начать раунд» at the same moment."""
    first = draft_round(client, admin_headers)
    created = client.post(
        "/api/v1/admin/rounds",
        json={"title": "Параллельный раунд", "game_config": first["game_config"]},
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    second_id = created.json()["id"]

    def start(round_id: int):
        return client.post(
            f"/api/v1/admin/rounds/{round_id}/start", headers=idempotency(admin_headers)
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(start, [first["id"], second_id]))

    codes = sorted(response.status_code for response in responses)
    assert codes == [200, 409], [response.text for response in responses]

    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM rounds WHERE status IN ('active', 'scoring')"
            )
            assert cursor.fetchone()[0] == 1
    finally:
        connection.close()


def test_a_completed_round_cannot_be_started_again(
    client, admin_headers, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    saved = put_scenario(client, round_id, participant["headers"], valid_chain(cards)).json()
    client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": saved["revision"]},
        headers=participant["headers"],
    )
    client.post(f"/api/v1/admin/rounds/{round_id}/score", headers=idempotency(admin_headers))

    response = client.post(
        f"/api/v1/admin/rounds/{round_id}/start", headers=idempotency(admin_headers)
    )
    assert response.status_code == 409
    assert response.json()["code"] == "round_locked"


# --------------------------------------------------------------------------
# Presets
# --------------------------------------------------------------------------


@pytest.fixture()
def preset(client, admin_headers) -> dict:
    config = draft_round(client, admin_headers)["game_config"]
    response = client.post(
        "/api/v1/admin/round-presets",
        json={
            "name": "Короткий мастер-класс",
            "description": "Быстрый раунд на 45 минут",
            "game_config": config,
        },
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_a_preset_round_trips_through_the_api(client, admin_headers, preset) -> None:
    assert preset["revision"] == 1
    listing = client.get("/api/v1/admin/round-presets", headers=admin_headers).json()
    assert [item["name"] for item in listing] == ["Короткий мастер-класс"]
    single = client.get(
        f"/api/v1/admin/round-presets/{preset['id']}", headers=admin_headers
    ).json()
    assert single["game_config"]["operations"]


def test_preset_names_are_unique(client, admin_headers, preset) -> None:
    response = client.post(
        "/api/v1/admin/round-presets",
        json={"name": preset["name"], "game_config": preset["game_config"]},
        headers=admin_headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "preset_name_taken"


def test_updating_a_preset_uses_optimistic_concurrency(
    client, admin_headers, preset
) -> None:
    config = copy.deepcopy(preset["game_config"])
    config["objectives"]["max_actions"] = 5
    stale = client.put(
        f"/api/v1/admin/round-presets/{preset['id']}",
        json={"expected_revision": 99, "game_config": config},
        headers=admin_headers,
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "preset_revision_conflict"

    updated = client.put(
        f"/api/v1/admin/round-presets/{preset['id']}",
        json={"expected_revision": preset["revision"], "game_config": config},
        headers=admin_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == 2
    assert updated.json()["game_config"]["objectives"]["max_actions"] == 5


def test_creating_a_round_from_a_preset_copies_the_configuration(
    client, admin_headers, preset
) -> None:
    created = client.post(
        "/api/v1/admin/rounds",
        json={"title": "Раунд из пресета", "preset_id": preset["id"]},
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    round_obj = created.json()
    assert round_obj["status"] == "draft", "loading a preset must not start anything"
    assert round_obj["preset_id"] == preset["id"]
    # A round copies every preset value and additionally freezes its own catalog.
    stored = {
        key: value
        for key, value in round_obj["game_config"].items()
        if key != "card_snapshots"
    }
    assert stored == preset["game_config"]
    assert round_obj["game_config"]["card_snapshots"]

    # Editing the preset afterwards leaves the round's own snapshot alone.
    config = copy.deepcopy(preset["game_config"])
    config["objectives"]["target_outflow"] = "999999.00"
    client.put(
        f"/api/v1/admin/round-presets/{preset['id']}",
        json={"expected_revision": 1, "game_config": config},
        headers=admin_headers,
    )
    unchanged = client.get(
        f"/api/v1/admin/rounds/{round_obj['id']}", headers=admin_headers
    ).json()
    assert unchanged["game_config"]["objectives"]["target_outflow"] != "999999.00"


def test_deleting_a_preset_requires_confirmation_and_keeps_its_rounds(
    client, admin_headers, preset
) -> None:
    created = client.post(
        "/api/v1/admin/rounds",
        json={"title": "Раунд из пресета", "preset_id": preset["id"]},
        headers=admin_headers,
    ).json()

    refused = client.delete(
        f"/api/v1/admin/round-presets/{preset['id']}", headers=admin_headers
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "confirmation_required"

    removed = client.delete(
        f"/api/v1/admin/round-presets/{preset['id']}?confirm=true", headers=admin_headers
    )
    assert removed.status_code == 204
    assert client.get("/api/v1/admin/round-presets", headers=admin_headers).json() == []

    survivor = client.get(
        f"/api/v1/admin/rounds/{created['id']}", headers=admin_headers
    ).json()
    assert survivor["preset_id"] is None
    assert survivor["game_config"]["operations"]


def test_an_invalid_preset_configuration_is_refused(client, admin_headers, preset) -> None:
    config = copy.deepcopy(preset["game_config"])
    config["operations"][0]["visible_params"] = [
        "channel",
        "context.time_of_day",
        "context.velocity",
    ]
    response = client.post(
        "/api/v1/admin/round-presets",
        json={"name": "Слишком много параметров", "game_config": config},
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_presets_and_lifecycle_are_admin_only(client, active_round) -> None:
    player = register_participant(client)
    for method, path, body in (
        ("get", "/api/v1/admin/round-presets", None),
        ("post", "/api/v1/admin/round-presets", {"name": "x", "game_config": {}}),
        (
            "post",
            f"/api/v1/admin/rounds/{active_round['id']}/stop",
            {"confirm": True},
        ),
        (
            "post",
            f"/api/v1/admin/rounds/{active_round['id']}/restart",
            {"confirm": True},
        ),
        ("post", f"/api/v1/admin/rounds/{active_round['id']}/start", None),
        ("get", f"/api/v1/admin/rounds/{active_round['id']}/scoring-plan", None),
    ):
        call = getattr(client, method)
        response = (
            call(path, json=body, headers=player["headers"])
            if body is not None
            else call(path, headers=player["headers"])
        )
        assert response.status_code == 403, (path, response.text)
        assert response.json()["code"] == "forbidden"
