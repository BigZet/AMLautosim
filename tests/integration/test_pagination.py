"""Cursor paging on every list the API serves.

`docs/api.md` promises `limit` plus an opaque `cursor` on the growing lists.
These tests hold the promise to the implementation: a caller that follows
`next_cursor` to the end must see every row exactly once.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import psycopg2
import pytest

from tests.helpers import put_scenario, valid_chain

ROSTER_SIZE = 130


def _insert_participants(dsn: str, count: int) -> None:
    """Create participants straight in the database.

    Registering them through the API would spend a bcrypt hash each; nothing
    here logs in, so the hash only has to be well-formed.
    """
    now = datetime.now(UTC)
    connection = psycopg2.connect(dsn)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO users (
                    email, display_name, hashed_password, role, is_blocked,
                    access_revision, failed_login_count, created_at, updated_at
                ) VALUES (%s, %s, %s, 'participant', false, 1, 0, %s, %s)
                """,
                [
                    (
                        f"bulk{index:04d}@example.com",
                        f"Участник {index:04d}",
                        "$2b$12$" + "x" * 53,
                        now,
                        now,
                    )
                    for index in range(count)
                ],
            )
    finally:
        connection.close()


def _walk(client, url, headers, params=None, page_limit=40):
    """Follow `next_cursor` to the end and return every row seen."""
    collected = []
    cursor = None
    for _ in range(page_limit):
        query = dict(params or {})
        if cursor:
            query["cursor"] = cursor
        response = client.get(url, params=query, headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        collected.extend(payload["rows"])
        cursor = payload["next_cursor"]
        if not cursor:
            return collected
    raise AssertionError("cursor never ran out: paging does not advance")


def test_the_whole_roster_is_reachable_one_page_at_a_time(
    client, admin_headers, active_round, db_dsn
):
    """An organiser who cannot see a participant cannot unblock them either."""
    _insert_participants(db_dsn, ROSTER_SIZE)
    url = f"/api/v1/admin/rounds/{active_round['id']}/participants"

    rows = _walk(client, url, admin_headers, {"limit": 25})

    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)), "a row was served twice"
    assert len(ids) == ROSTER_SIZE
    assert ids == sorted(ids), "paging must not reorder the roster"


def test_the_roster_fits_a_full_workshop_in_one_page(
    client, admin_headers, active_round, db_dsn
):
    """500 is the audience `docs/operations.md` plans for."""
    _insert_participants(db_dsn, ROSTER_SIZE)
    url = f"/api/v1/admin/rounds/{active_round['id']}/participants"

    whole = client.get(url, params={"limit": 500}, headers=admin_headers)
    assert whole.status_code == 200, whole.text
    assert len(whole.json()["rows"]) == ROSTER_SIZE
    assert whole.json()["next_cursor"] is None

    too_large = client.get(url, params={"limit": 501}, headers=admin_headers)
    assert too_large.status_code == 422


def test_a_scenario_filter_does_not_shorten_a_page(
    client, admin_headers, active_round, db_dsn, participant, cards
):
    """Filtering after the fetch made a full page look like the last one."""
    _insert_participants(db_dsn, ROSTER_SIZE)
    saved = put_scenario(
        client,
        active_round["id"],
        participant["headers"],
        valid_chain(cards),
        expected_revision=0,
    )
    assert saved.status_code == 200, saved.text
    url = f"/api/v1/admin/rounds/{active_round['id']}/participants"

    without = client.get(
        url, params={"scenario_status": "none", "limit": 10}, headers=admin_headers
    )
    assert without.status_code == 200, without.text
    # A full page must be full, and must promise the next one.
    assert len(without.json()["rows"]) == 10
    assert without.json()["next_cursor"]
    assert all(row["scenario_status"] == "none" for row in without.json()["rows"])

    drafting = client.get(
        url, params={"scenario_status": "draft"}, headers=admin_headers
    )
    assert [row["id"] for row in drafting.json()["rows"]] == [participant["id"]]


def test_a_cursor_moves_the_participants_own_round_list(
    client, participant, active_round
):
    """`docs/api.md` documents `?limit=&cursor=` on /rounds/mine."""
    first = client.get(
        "/api/v1/rounds/mine", params={"limit": 1}, headers=participant["headers"]
    )
    assert first.status_code == 200, first.text
    assert [row["id"] for row in first.json()["rows"]] == [active_round["id"]]
    # One round exists, so the first page is also the last.
    assert first.json()["next_cursor"] is None


def test_a_damaged_cursor_is_refused_rather_than_restarted(
    client, admin_headers, active_round
):
    """Serving page one for a broken cursor turns a paging loop into a circle."""
    response = client.get(
        f"/api/v1/admin/rounds/{active_round['id']}/participants",
        params={"cursor": "not-a-cursor"},
        headers=admin_headers,
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_cursor"


def test_the_audit_trail_pages_newest_first(client, admin_headers, active_round):
    """The trail is append-only, so a timestamp keyset never repeats a row."""
    round_id = active_round["id"]
    for index in range(6):
        response = client.put(
            f"/api/v1/admin/rounds/{round_id}/participants/0/access",
            headers=admin_headers,
            json={"is_blocked": False, "reason": f"проверка {index}"},
        )
        # The participant does not exist; the point is only to have events.
        assert response.status_code in (404, 422), response.text

    url = f"/api/v1/admin/rounds/{round_id}/audit-events"
    everything = client.get(url, headers=admin_headers).json()["rows"]
    paged = _walk(client, url, admin_headers, {"limit": 1})

    assert [row["id"] for row in paged] == [row["id"] for row in everything]


@pytest.fixture()
def completed_round(client, admin_headers, participant, second_participant, active_round, cards):
    """A round with two scored scenarios."""
    round_id = active_round["id"]
    for player in (participant, second_participant):
        saved = put_scenario(
            client, round_id, player["headers"], valid_chain(cards), expected_revision=0
        )
        assert saved.status_code == 200, saved.text
        submitted = client.post(
            f"/api/v1/rounds/{round_id}/scenario/submit",
            json={"expected_revision": saved.json()["revision"]},
            headers=player["headers"],
        )
        assert submitted.status_code == 200, submitted.text
    scored = client.post(
        f"/api/v1/admin/rounds/{round_id}/score",
        headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert scored.status_code == 200, scored.text
    return round_id


def test_the_masked_board_keeps_counting_across_pages(client, completed_round):
    """«Игрок #1» on every page would misread as a two-way tie for first."""
    url = f"/api/v1/rounds/{completed_round}/leaderboard"

    whole = client.get(url).json()["rows"]
    assert [row["display_name"] for row in whole] == ["Игрок #1", "Игрок #2"]

    paged = _walk(client, url, None, {"limit": 1})
    assert [row["display_name"] for row in paged] == ["Игрок #1", "Игрок #2"]
    assert [row["rank"] for row in paged] == [row["rank"] for row in whole]
