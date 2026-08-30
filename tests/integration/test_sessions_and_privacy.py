"""Technical login metadata and leaderboard privacy.

Two separate promises are checked here:

* an administrator can see *how* a participant connected — address, browser,
  language, session lifetime — and nobody else can;
* a leaderboard nickname does not leave the server until somebody explicitly
  asks for it, so a provocative nickname cannot appear on a projector.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest

from src.aml_workshop_simulator.core import request_meta
from src.aml_workshop_simulator.core.config import settings
from tests.conftest import PARTICIPANT_PASSWORD, register_participant
from tests.helpers import put_scenario, valid_chain

PROVOCATIVE_NICKNAME = "ОтмываюМиллионы666"
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def login(client, email: str, headers: dict[str, str] | None = None) -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PARTICIPANT_PASSWORD, "audience": "play"},
        headers=headers or {},
    )
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------
# What is recorded at login
# --------------------------------------------------------------------------


def test_login_records_the_browser_and_the_address(
    client, admin_headers, active_round
) -> None:
    player = register_participant(client, display_name="С устройством")
    login(
        client,
        player["email"],
        {"User-Agent": CHROME_UA, "Accept-Language": "ru-RU,ru;q=0.9"},
    )

    detail = client.get(
        f"/api/v1/admin/rounds/{active_round['id']}/participants/{player['id']}",
        headers=admin_headers,
    ).json()
    sessions = detail["sessions"]
    assert len(sessions) == 2, "the fixture login plus this one"
    latest = sessions[0]
    assert latest["audience"] == "play"
    assert latest["user_agent"] == CHROME_UA
    assert latest["accept_language"] == "ru-RU,ru;q=0.9"
    assert latest["ip_address"]
    assert latest["is_active"] is True
    assert latest["revoked_at"] is None

    user = detail["user"]
    assert user["created_at"]
    assert user["first_login_at"]
    assert user["last_login_at"]
    assert user["first_login_at"] <= user["last_login_at"]
    assert user["active_session_count"] == 2
    assert user["total_session_count"] == 2
    assert user["last_ip_address"] == latest["ip_address"]


def test_the_first_login_time_is_recorded_once(client, admin_headers, active_round) -> None:
    player = register_participant(client, display_name="Повторный вход")

    def first_login_at() -> str:
        return client.get(
            f"/api/v1/admin/rounds/{active_round['id']}/participants/{player['id']}",
            headers=admin_headers,
        ).json()["user"]["first_login_at"]

    original = first_login_at()
    login(client, player["email"])
    assert first_login_at() == original


def test_a_revoked_session_is_visible_with_its_reason(
    client, admin_headers, active_round
) -> None:
    player = register_participant(client, display_name="Вышел")
    client.delete("/api/v1/auth/session", headers=player["headers"])

    detail = client.get(
        f"/api/v1/admin/rounds/{active_round['id']}/participants/{player['id']}",
        headers=admin_headers,
    ).json()
    session = detail["sessions"][0]
    assert session["is_active"] is False
    assert session["revoke_reason"] == "logout"
    assert detail["user"]["active_session_count"] == 0
    assert detail["user"]["total_session_count"] == 1


def test_blocking_shows_every_session_as_revoked(
    client, admin_headers, active_round
) -> None:
    player = register_participant(client, display_name="Заблокированный")
    login(client, player["email"])

    response = client.put(
        f"/api/v1/admin/rounds/{active_round['id']}/participants/{player['id']}/access",
        json={
            "blocked": True,
            "reason": "Нарушение правил мастер-класса",
            "expected_access_revision": 1,
        },
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text

    detail = client.get(
        f"/api/v1/admin/rounds/{active_round['id']}/participants/{player['id']}",
        headers=admin_headers,
    ).json()
    assert detail["user"]["active_session_count"] == 0
    assert all(item["revoke_reason"] == "account_blocked" for item in detail["sessions"])


def test_no_secret_is_stored_next_to_the_session(client, db_dsn, active_round) -> None:
    """Only a hash of the identifier is persisted, never the identifier itself."""
    player = register_participant(client, display_name="Секреты")
    connection = psycopg2.connect(db_dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT session_id_hash, ip_address, user_agent FROM sessions "
                "WHERE user_id = %s",
                (player["id"],),
            )
            row = cursor.fetchone()
            assert len(row[0]) == 64
            assert player["session_id"] not in row[0]
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'sessions'"
            )
            columns = {name for (name,) in cursor.fetchall()}
            assert "password" not in columns
            assert "session_id" not in columns
    finally:
        connection.close()


def test_session_metadata_is_never_exposed_to_participants(
    client, participant, active_round
) -> None:
    """The player API carries no address, browser or session inventory."""
    session = client.get("/api/v1/auth/session", headers=participant["headers"]).json()
    assert set(session) == {
        "id",
        "display_name",
        "role",
        "audience",
        "is_blocked",
        "access_revision",
    }

    forbidden = client.get(
        f"/api/v1/admin/rounds/{active_round['id']}/participants/{participant['id']}",
        headers=participant["headers"],
    )
    assert forbidden.status_code == 403

    body = client.get(
        f"/api/v1/rounds/{active_round['id']}/scenario", headers=participant["headers"]
    ).text
    assert "ip_address" not in body
    assert "user_agent" not in body


# --------------------------------------------------------------------------
# Forwarded addresses
# --------------------------------------------------------------------------


def test_an_untrusted_forwarded_header_is_ignored(
    client, admin_headers, active_round
) -> None:
    """`X-Forwarded-For` from an unknown peer must not reach the database."""
    player = register_participant(client, display_name="Подделка адреса")
    login(client, player["email"], {"X-Forwarded-For": "203.0.113.7"})

    detail = client.get(
        f"/api/v1/admin/rounds/{active_round['id']}/participants/{player['id']}",
        headers=admin_headers,
    ).json()
    assert detail["sessions"][0]["ip_address"] != "203.0.113.7"


def test_a_trusted_proxy_is_believed(client, admin_headers, active_round, monkeypatch) -> None:
    player = register_participant(client, display_name="За прокси")
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "127.0.0.1/32,::1/128")
    login(
        client,
        player["email"],
        {"X-Forwarded-For": "198.51.100.42, 127.0.0.1"},
    )

    detail = client.get(
        f"/api/v1/admin/rounds/{active_round['id']}/participants/{player['id']}",
        headers=admin_headers,
    ).json()
    assert detail["sessions"][0]["ip_address"] == "198.51.100.42"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("192.0.2.10", "192.0.2.10"),
        ("192.0.2.10:5555", "192.0.2.10"),
        ("2001:db8::1", "2001:db8::1"),
        ("[2001:db8::1]:443", "2001:db8::1"),
        ("not-an-address", None),
        ("", None),
        (None, None),
    ],
)
def test_addresses_are_normalised_for_ipv4_and_ipv6(raw, expected) -> None:
    assert request_meta.normalise_ip(raw) == expected


def test_an_ipv6_client_is_stored(client, admin_headers, active_round, monkeypatch) -> None:
    player = register_participant(client, display_name="IPv6")
    monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "127.0.0.1/32")
    login(client, player["email"], {"X-Forwarded-For": "2001:db8::dead:beef"})
    detail = client.get(
        f"/api/v1/admin/rounds/{active_round['id']}/participants/{player['id']}",
        headers=admin_headers,
    ).json()
    assert detail["sessions"][0]["ip_address"] == "2001:db8::dead:beef"


# --------------------------------------------------------------------------
# Leaderboard privacy
# --------------------------------------------------------------------------


@pytest.fixture()
def completed_round(client, admin_headers, active_round, cards) -> dict:
    """One finished round whose single participant has a provocative nickname."""
    player = register_participant(client, display_name=PROVOCATIVE_NICKNAME)
    round_id = active_round["id"]
    saved = put_scenario(client, round_id, player["headers"], valid_chain(cards)).json()
    client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": saved["revision"]},
        headers=player["headers"],
    )
    scored = client.post(
        f"/api/v1/admin/rounds/{round_id}/score",
        headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert scored.status_code == 200, scored.text
    return {"round_id": round_id, "player": player}


def test_the_public_board_hides_the_nickname_by_default(
    client, completed_round
) -> None:
    round_id = completed_round["round_id"]
    player = completed_round["player"]

    response = client.get(f"/api/v1/rounds/{round_id}/leaderboard")
    assert response.status_code == 200
    body = response.text
    assert PROVOCATIVE_NICKNAME not in body
    assert player["email"] not in body

    page = response.json()
    assert page["revealed"] is False
    row = page["rows"][0]
    assert row["display_name"] == "Игрок #1"
    assert row["masked"] is True


def test_only_the_organiser_can_ask_for_the_nickname(
    client, admin_headers, completed_round
) -> None:
    """The board goes on a projector, so revealing it is the host's command.

    A participant revealing the room's nicknames on their own phone, or an
    outsider who merely knows the round id doing it over HTTP, is exactly the
    disclosure the masking exists to prevent.
    """
    url = f"/api/v1/rounds/{completed_round['round_id']}/leaderboard?reveal=true"

    anonymous = client.get(url)
    assert anonymous.status_code == 401, anonymous.text
    assert PROVOCATIVE_NICKNAME not in anonymous.text

    as_participant = client.get(url, headers=completed_round["player"]["headers"])
    assert as_participant.status_code == 403, as_participant.text
    assert PROVOCATIVE_NICKNAME not in as_participant.text

    page = client.get(url, headers=admin_headers).json()
    assert page["revealed"] is True
    assert page["rows"][0]["display_name"] == PROVOCATIVE_NICKNAME
    assert page["rows"][0]["masked"] is False


def test_masking_keeps_the_placement_and_the_own_row_marker(
    client, admin_headers, completed_round
) -> None:
    round_id = completed_round["round_id"]
    player = completed_round["player"]
    masked = client.get(
        f"/api/v1/rounds/{round_id}/leaderboard", headers=player["headers"]
    ).json()
    revealed = client.get(
        f"/api/v1/rounds/{round_id}/leaderboard?reveal=true", headers=admin_headers
    ).json()

    assert [row["rank"] for row in masked["rows"]] == [
        row["rank"] for row in revealed["rows"]
    ]
    assert [row["game_score"] for row in masked["rows"]] == [
        row["game_score"] for row in revealed["rows"]
    ]
    # The player can still find themselves without their name being disclosed.
    assert masked["rows"][0]["is_current_user"] is True
    assert masked["rows"][0]["display_name"] == "Игрок #1"


def test_the_admin_board_still_shows_real_identities(
    client, admin_headers, completed_round
) -> None:
    round_id = completed_round["round_id"]
    board = client.get(
        f"/api/v1/admin/rounds/{round_id}/leaderboard", headers=admin_headers
    ).json()
    assert board["rows"][0]["display_name"] == PROVOCATIVE_NICKNAME
    assert board["rows"][0]["email"] == completed_round["player"]["email"]


def test_the_admin_participant_search_still_finds_the_real_nickname(
    client, admin_headers, completed_round
) -> None:
    round_id = completed_round["round_id"]
    page = client.get(
        f"/api/v1/admin/rounds/{round_id}/participants",
        params={"query": "Отмываю"},
        headers=admin_headers,
    ).json()
    assert [row["display_name"] for row in page["rows"]] == [PROVOCATIVE_NICKNAME]
