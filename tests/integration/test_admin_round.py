"""Round lifecycle, atomic scoring, adjustments and audit."""

from __future__ import annotations

import copy
import uuid

import psycopg2
import pytest

from tests.helpers import put_scenario, valid_chain


def submit_valid_chain(client, round_id, headers, cards) -> dict:
    saved = put_scenario(client, round_id, headers, valid_chain(cards)).json()
    submitted = client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": saved["revision"]},
        headers=headers,
    )
    assert submitted.status_code == 200, submitted.text
    return submitted.json()


def score(client, round_id, admin_headers):
    return client.post(
        f"/api/v1/admin/rounds/{round_id}/score",
        headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
    )


# --------------------------------------------------------------------------
# Round configuration
# --------------------------------------------------------------------------


def test_draft_config_update_uses_the_config_revision(client, admin_headers) -> None:
    rounds = client.get("/api/v1/admin/rounds", headers=admin_headers).json()
    draft = next(item for item in rounds if item["status"] == "draft")

    stale = client.put(
        f"/api/v1/admin/rounds/{draft['id']}",
        json={"expected_config_revision": 99, "title": "Другое название"},
        headers=admin_headers,
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "round_config_conflict"

    ok = client.put(
        f"/api/v1/admin/rounds/{draft['id']}",
        json={"expected_config_revision": draft["config_revision"], "title": "Новое название"},
        headers=admin_headers,
    )
    assert ok.status_code == 200
    assert ok.json()["config_revision"] == draft["config_revision"] + 1


def test_activation_pins_a_config_version_and_locks_the_config(
    client, admin_headers, active_round
) -> None:
    assert active_round["game_config"]["config_version"].startswith("round-config-v2:sha256:")
    locked = client.put(
        f"/api/v1/admin/rounds/{active_round['id']}",
        json={"expected_config_revision": active_round["config_revision"], "title": "Ещё"},
        headers=admin_headers,
    )
    assert locked.status_code == 409
    assert locked.json()["code"] == "round_config_locked"


def test_activation_is_idempotent(client, admin_headers, active_round) -> None:
    again = client.post(
        f"/api/v1/admin/rounds/{active_round['id']}/activate",
        headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert again.status_code == 200
    assert again.json()["activated_at"] == active_round["activated_at"]


def test_a_second_active_round_is_refused(client, admin_headers, active_round) -> None:
    created = client.post(
        "/api/v1/admin/rounds",
        json={"title": "Второй раунд", "game_config": active_round["game_config"]},
        headers=admin_headers,
    )
    assert created.status_code == 201
    response = client.post(
        f"/api/v1/admin/rounds/{created.json()['id']}/activate",
        headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "active_round_exists"


def test_unknown_ruleset_version_is_refused(client, admin_headers, active_round) -> None:
    """A ruleset this build cannot run is rejected when the round is created."""
    config = copy.deepcopy(active_round["game_config"])
    config["ruleset_version"] = "game-rules-v99"
    response = client.post(
        "/api/v1/admin/rounds",
        json={"title": "Раунд с чужими правилами", "game_config": config},
        headers=admin_headers,
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "round_configuration_invalid"
    assert "game-rules-v99" in response.json()["message"]


def test_broken_weights_are_refused(client, admin_headers) -> None:
    """Leaderboard weights that do not sum to 1 never reach the database."""
    rounds = client.get("/api/v1/admin/rounds", headers=admin_headers).json()
    draft = next(item for item in rounds if item["status"] == "draft")
    config = copy.deepcopy(draft["game_config"])
    config["leaderboard"]["weights"] = {"stealth": "0.70", "resources": "0.40"}
    update = client.put(
        f"/api/v1/admin/rounds/{draft['id']}",
        json={
            "expected_config_revision": draft["config_revision"],
            "game_config": config,
        },
        headers=admin_headers,
    )
    assert update.status_code == 422, update.text
    assert update.json()["code"] == "validation_error"

    unchanged = client.get(
        f"/api/v1/admin/rounds/{draft['id']}", headers=admin_headers
    ).json()
    assert unchanged["game_config"]["leaderboard"]["weights"] == {
        "resources": "0.40",
        "stealth": "0.60",
    }
    activated = client.post(
        f"/api/v1/admin/rounds/{draft['id']}/activate",
        headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert activated.status_code == 200, activated.text


def test_only_one_active_round_at_the_database_level(client, admin_headers, active_round, db_dsn) -> None:
    connection = psycopg2.connect(db_dsn)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            with pytest.raises(psycopg2.errors.UniqueViolation):
                cursor.execute(
                    "INSERT INTO rounds (title, status, config_revision, game_config, "
                    "created_by_user_id, created_at) VALUES "
                    "('Дубль', 'active', 1, '{}'::jsonb, 1, now())"
                )
    finally:
        connection.close()


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def test_scoring_without_submissions_is_refused(client, admin_headers, active_round) -> None:
    response = score(client, active_round["id"], admin_headers)
    assert response.status_code == 400
    assert response.json()["code"] == "no_submissions"


def test_scoring_publishes_results_and_completes_the_round(
    client, admin_headers, participant, active_round, cards, db_dsn
) -> None:
    round_id = active_round["id"]
    submit_valid_chain(client, round_id, participant["headers"], cards)

    summary = score(client, round_id, admin_headers)
    assert summary.status_code == 200
    payload = summary.json()
    assert payload["status"] == "completed"
    assert payload["submitted_count"] == payload["scored_count"] == 1

    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT status, scoring_summary FROM rounds WHERE id = %s", (round_id,))
            status, stored_summary = cursor.fetchone()
            cursor.execute("SELECT count(*) FROM scoring_results")
            results = cursor.fetchone()[0]
            cursor.execute("SELECT status FROM scenarios WHERE round_id = %s", (round_id,))
            scenario_status = cursor.fetchone()[0]
    finally:
        connection.close()
    assert status == "completed"
    assert stored_summary["scored_count"] == 1
    assert results == 1
    assert scenario_status == "scored"


def test_drafts_are_excluded_from_scoring(
    client, admin_headers, participant, second_participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    submit_valid_chain(client, round_id, participant["headers"], cards)
    put_scenario(client, round_id, second_participant["headers"], valid_chain(cards))

    payload = score(client, round_id, admin_headers).json()
    assert payload["submitted_count"] == 1
    assert payload["excluded_draft_count"] == 1

    result = client.get(
        f"/api/v1/rounds/{round_id}/result", headers=second_participant["headers"]
    )
    assert result.status_code == 200
    assert result.json() is None


def test_repeated_scoring_returns_the_stored_summary(
    client, admin_headers, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    submit_valid_chain(client, round_id, participant["headers"], cards)
    first = score(client, round_id, admin_headers).json()
    second = score(client, round_id, admin_headers).json()
    assert second["completed_at"] == first["completed_at"]
    assert second["scored_count"] == first["scored_count"]


def test_completed_round_blocks_editing_and_submitting(
    client, admin_headers, participant, second_participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    submit_valid_chain(client, round_id, participant["headers"], cards)
    saved = put_scenario(client, round_id, second_participant["headers"], valid_chain(cards)).json()
    score(client, round_id, admin_headers)

    edit = put_scenario(
        client,
        round_id,
        second_participant["headers"],
        valid_chain(cards),
        expected_revision=saved["revision"],
    )
    assert edit.status_code == 409
    assert edit.json()["code"] == "round_locked"

    submit = client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": saved["revision"]},
        headers=second_participant["headers"],
    )
    assert submit.status_code == 409
    assert submit.json()["code"] == "round_locked"


def test_participant_sees_the_result_and_the_public_board(
    client, admin_headers, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    submit_valid_chain(client, round_id, participant["headers"], cards)
    score(client, round_id, admin_headers)

    result = client.get(
        f"/api/v1/rounds/{round_id}/result", headers=participant["headers"]
    ).json()
    assert result["base"]["risk_label"] in {"normal", "review", "suspicious"}
    assert 0 <= float(result["base"]["game_score"]) <= 100
    assert result["leaderboard"]["rank"] == 1

    board = client.get(
        f"/api/v1/rounds/{round_id}/leaderboard", headers=participant["headers"]
    ).json()
    assert len(board["rows"]) == 1
    assert board["rows"][0]["is_current_user"] is True


def test_submitted_chain_is_visible_to_the_admin(
    client, admin_headers, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    submitted = submit_valid_chain(client, round_id, participant["headers"], cards)
    detail = client.get(
        f"/api/v1/admin/rounds/{round_id}/participants/{participant['id']}",
        headers=admin_headers,
    ).json()
    assert detail["scenario"]["status"] == "submitted"
    assert len(detail["scenario"]["steps"]) == len(submitted["steps"])
    assert detail["scenario"]["steps"][0]["context"]["channel"] == "bank"


# --------------------------------------------------------------------------
# Access control and adjustments
# --------------------------------------------------------------------------


def test_block_revokes_sessions_and_keeps_the_scenario(
    client, admin_headers, participant, active_round, cards, db_dsn
) -> None:
    round_id = active_round["id"]
    saved = put_scenario(client, round_id, participant["headers"], valid_chain(cards)).json()

    blocked = client.put(
        f"/api/v1/admin/rounds/{round_id}/participants/{participant['id']}/access",
        json={
            "blocked": True,
            "reason": "Проверка учетной записи организатором",
            "expected_access_revision": 1,
        },
        headers=admin_headers,
    )
    assert blocked.status_code == 200
    assert blocked.json()["is_blocked"] is True

    denied = client.get(
        f"/api/v1/rounds/{round_id}/scenario", headers=participant["headers"]
    )
    assert denied.status_code in (401, 403)

    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM sessions WHERE user_id = %s AND revoked_at IS NULL",
                (participant["id"],),
            )
            assert cursor.fetchone()[0] == 0
            cursor.execute("SELECT count(*) FROM scenarios WHERE id = %s", (saved["id"],))
            assert cursor.fetchone()[0] == 1
    finally:
        connection.close()


def test_unblock_requires_a_new_login(client, admin_headers, participant, active_round) -> None:
    round_id = active_round["id"]
    client.put(
        f"/api/v1/admin/rounds/{round_id}/participants/{participant['id']}/access",
        json={"blocked": True, "reason": "Временная блокировка участника",
              "expected_access_revision": 1},
        headers=admin_headers,
    )
    unblocked = client.put(
        f"/api/v1/admin/rounds/{round_id}/participants/{participant['id']}/access",
        json={"blocked": False, "reason": "Проверка завершена, доступ возвращен",
              "expected_access_revision": 2},
        headers=admin_headers,
    )
    assert unblocked.status_code == 200
    # The old session stays revoked: a new login is required.
    assert client.get(
        "/api/v1/auth/session", headers=participant["headers"]
    ).status_code == 401
    again = client.post(
        "/api/v1/auth/login",
        json={"email": participant["email"], "password": "correct-horse-42", "audience": "play"},
    )
    assert again.status_code == 200


def test_admin_cannot_block_itself(client, admin_headers, active_round) -> None:
    profile = client.get("/api/v1/auth/session", headers=admin_headers).json()
    response = client.put(
        f"/api/v1/admin/rounds/{active_round['id']}/participants/{profile['id']}/access",
        json={"blocked": True, "reason": "Попытка самоблокировки администратора",
              "expected_access_revision": 1},
        headers=admin_headers,
    )
    assert response.status_code == 403


def test_blocked_participant_is_hidden_from_the_public_board_only(
    client, admin_headers, participant, second_participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    submit_valid_chain(client, round_id, participant["headers"], cards)
    submit_valid_chain(client, round_id, second_participant["headers"], cards)
    score(client, round_id, admin_headers)

    client.put(
        f"/api/v1/admin/rounds/{round_id}/participants/{participant['id']}/access",
        json={"blocked": True, "reason": "Исключение из публичного рейтинга",
              "expected_access_revision": 1},
        headers=admin_headers,
    )

    public = client.get(f"/api/v1/rounds/{round_id}/leaderboard").json()
    assert all(row["display_name"] != participant["display_name"] for row in public["rows"])

    admin_board = client.get(
        f"/api/v1/admin/rounds/{round_id}/leaderboard", headers=admin_headers
    ).json()
    assert any(row["participant_id"] == participant["id"] for row in admin_board["rows"])


def test_adjustment_changes_effective_but_not_base(
    client, admin_headers, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    submit_valid_chain(client, round_id, participant["headers"], cards)
    score(client, round_id, admin_headers)
    before = client.get(
        f"/api/v1/rounds/{round_id}/result", headers=participant["headers"]
    ).json()

    adjusted = client.put(
        f"/api/v1/admin/rounds/{round_id}/participants/{participant['id']}"
        "/leaderboard-adjustment",
        json={
            "expected_revision": 0,
            "game_score_override": "88.00",
            "reason": "Коррекция после подтвержденной технической ошибки",
        },
        headers=admin_headers,
    )
    assert adjusted.status_code == 200
    assert adjusted.json()["revision"] == 1

    after = client.get(
        f"/api/v1/rounds/{round_id}/result", headers=participant["headers"]
    ).json()
    assert after["base"] == before["base"]
    assert after["leaderboard"]["effective_game_score"] == "88.00"
    assert after["leaderboard"]["is_adjusted"] is True

    conflict = client.put(
        f"/api/v1/admin/rounds/{round_id}/participants/{participant['id']}"
        "/leaderboard-adjustment",
        json={
            "expected_revision": 0,
            "game_score_override": "70.00",
            "reason": "Повторная попытка с устаревшей ревизией",
        },
        headers=admin_headers,
    )
    assert conflict.status_code == 409

    cleared = client.delete(
        f"/api/v1/admin/rounds/{round_id}/participants/{participant['id']}"
        "/leaderboard-adjustment?expected_revision=1",
        headers=admin_headers,
    )
    assert cleared.status_code == 204
    restored = client.get(
        f"/api/v1/rounds/{round_id}/result", headers=participant["headers"]
    ).json()
    assert restored["leaderboard"]["effective_game_score"] == before["base"]["game_score"]


def test_adjustment_without_a_result_is_refused(
    client, admin_headers, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    put_scenario(client, round_id, participant["headers"], valid_chain(cards))
    response = client.put(
        f"/api/v1/admin/rounds/{round_id}/participants/{participant['id']}"
        "/leaderboard-adjustment",
        json={
            "expected_revision": 0,
            "game_score_override": "80.00",
            "reason": "Корректировка до расчета результата",
        },
        headers=admin_headers,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "result_not_available"


def test_audit_trail_records_admin_actions(
    client, admin_headers, participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    submit_valid_chain(client, round_id, participant["headers"], cards)
    score(client, round_id, admin_headers)
    client.put(
        f"/api/v1/admin/rounds/{round_id}/participants/{participant['id']}/access",
        json={"blocked": True, "reason": "Проверка аудита блокировки",
              "expected_access_revision": 1},
        headers=admin_headers,
    )

    events = client.get(
        f"/api/v1/admin/rounds/{round_id}/audit-events", headers=admin_headers
    ).json()["rows"]
    types = {event["event_type"] for event in events}
    assert {"round_created", "round_activated", "round_scored", "participant_blocked"} <= types
    serialized = str(events)
    assert participant["email"] not in serialized
    assert participant["session_id"] not in serialized


def test_stats_reflect_the_database(
    client, admin_headers, participant, second_participant, active_round, cards
) -> None:
    round_id = active_round["id"]
    submit_valid_chain(client, round_id, participant["headers"], cards)
    put_scenario(client, round_id, second_participant["headers"], valid_chain(cards))

    stats = client.get(
        f"/api/v1/admin/rounds/{round_id}/stats", headers=admin_headers
    ).json()
    assert stats["registered_users"] == 2
    assert stats["submitted_scenarios"] == 1
    assert stats["draft_scenarios"] == 1
    assert stats["without_scenario"] == 0
