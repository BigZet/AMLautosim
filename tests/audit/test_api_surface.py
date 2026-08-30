"""Аудиторские проверки HTTP-контракта.

Фиксируют поведение, найденное независимой ревизией: границы выдачи, отсутствие
курсорной постраничности и доступность раскрытия ников без сессии.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import psycopg2
import pytest

from tests.conftest import register_participant
from tests.helpers import put_scenario, valid_chain


# --------------------------------------------------------------------------
# B-1. Список участников обрезан 100 строками и не имеет курсора
# --------------------------------------------------------------------------


def _insert_participants(dsn: str, count: int) -> None:
    """Быстро создаёт участников напрямую в БД: bcrypt на 101 регистрацию долгий."""
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
                        "$2b$12$" + "x" * 53,  # непроверяемый хеш: вход не выполняется
                        now,
                        now,
                    )
                    for index in range(count)
                ],
            )
    finally:
        connection.close()


def test_admin_participant_list_is_capped_at_100_rows_without_a_cursor(
    client, admin_headers, active_round, db_dsn
):
    """Дефект: организатор не может увидеть больше 100 участников.

    `limit` объявлен как `Query(default=100, ge=1, le=100)`, `next_cursor`
    всегда `null`, а обрезание выполняется в Python после выборки всех строк.
    Мастер-класс рассчитан на аудиторию до 500 человек.
    """
    _insert_participants(db_dsn, 130)

    response = client.get(
        f"/api/v1/admin/rounds/{active_round['id']}/participants",
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["rows"]) == 100
    assert payload["next_cursor"] is None

    # Больший limit контракт не принимает.
    too_large = client.get(
        f"/api/v1/admin/rounds/{active_round['id']}/participants",
        params={"limit": 200},
        headers=admin_headers,
    )
    assert too_large.status_code == 422


def test_documented_cursor_parameter_is_ignored_by_rounds_mine(
    client, participant, active_round
):
    """`docs/api.md` описывает `GET /rounds/mine?limit=10&cursor=...`.

    Параметр `cursor` не объявлен в обработчике: он молча игнорируется, а
    `next_cursor` всегда `null`.
    """
    response = client.get(
        "/api/v1/rounds/mine",
        params={"limit": 10, "cursor": "opaque-cursor"},
        headers=participant["headers"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["next_cursor"] is None


# --------------------------------------------------------------------------
# B-2. Раскрытие ников не требует сессии
# --------------------------------------------------------------------------


@pytest.fixture()
def completed_round(client, admin_headers, participant, active_round, cards):
    """Раунд с одним отправленным и оценённым сценарием."""
    round_id = active_round["id"]
    saved = put_scenario(
        client, round_id, participant["headers"], valid_chain(cards), expected_revision=0
    )
    assert saved.status_code == 200, saved.text
    submitted = client.post(
        f"/api/v1/rounds/{round_id}/scenario/submit",
        json={"expected_revision": saved.json()["revision"]},
        headers=participant["headers"],
    )
    assert submitted.status_code == 200, submitted.text
    scored = client.post(
        f"/api/v1/admin/rounds/{round_id}/score",
        headers={**admin_headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert scored.status_code == 200, scored.text
    return round_id


def test_reveal_true_returns_real_nicknames_to_an_anonymous_caller(
    client, participant, completed_round
):
    """Дефект приватности: `?reveal=true` не требует ни сессии, ни роли.

    `docs/security.md` §13 описывает раскрытие как «явную команду ведущего»;
    в коде `reveal` — обычный query-параметр без какой-либо авторизации.
    """
    masked = client.get(f"/api/v1/rounds/{completed_round}/leaderboard")
    assert masked.status_code == 200, masked.text
    assert masked.json()["rows"][0]["display_name"].startswith("Игрок #")
    assert masked.json()["rows"][0]["masked"] is True

    revealed = client.get(
        f"/api/v1/rounds/{completed_round}/leaderboard", params={"reveal": "true"}
    )
    assert revealed.status_code == 200, revealed.text
    row = revealed.json()["rows"][0]
    assert row["masked"] is False
    assert row["display_name"] == participant["display_name"]


def test_any_participant_can_reveal_every_nickname(
    client, second_participant, participant, completed_round
):
    """Кнопка «Показать все ники» доступна каждому участнику, не только ведущему."""
    revealed = client.get(
        f"/api/v1/rounds/{completed_round}/leaderboard",
        params={"reveal": "true"},
        headers=second_participant["headers"],
    )
    assert revealed.status_code == 200, revealed.text
    names = {row["display_name"] for row in revealed.json()["rows"]}
    assert participant["display_name"] in names


# --------------------------------------------------------------------------
# B-3. Завершённый раунд не виден участнику без сценария
# --------------------------------------------------------------------------


def test_completed_round_disappears_for_a_participant_without_a_scenario(
    client, completed_round
):
    """Дефект: страницы «Результат» и «Лидерборд» показывают «Раундов пока нет».

    `GET /rounds/mine` перечисляет только раунды, в которых у участника есть
    строка `scenarios`, плюс текущий active/stopped/scoring. Участник, не
    успевший сохранить черновик, после завершения раунда теряет доступ к
    публичному лидерборду через UI: обе страницы строят выпадающий список
    именно из `/rounds/mine`.
    """
    latecomer = register_participant(client, display_name="Опоздавший")

    mine = client.get("/api/v1/rounds/mine", headers=latecomer["headers"])
    assert mine.status_code == 200, mine.text
    assert mine.json()["rows"] == []

    # При этом сам лидерборд раунда доступен и не пуст.
    board = client.get(f"/api/v1/rounds/{completed_round}/leaderboard")
    assert board.status_code == 200, board.text
    assert board.json()["rows"], "лидерборд завершённого раунда не пуст"
