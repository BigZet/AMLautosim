"""Stable account traversal and literal organizer search on PostgreSQL."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import insert

from src.aml_workshop_simulator.db.models.users import User
from src.aml_workshop_simulator.db.session import AsyncSessionLocal


def add_accounts(names):
    async def run():
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                insert(User).returning(User.id),
                [
                    {
                        "email": f"fixture-{i}@example.com",
                        "display_name": name,
                        "role": "participant",
                        "hashed_password": "unused-fixture",
                    }
                    for i, name in enumerate(names)
                ],
            )
            ids = list(result.scalars())
            await db.commit()
            return ids

    return asyncio.run(run())


def test_all_accounts_reachable_during_registration(api, admin, round_id):
    expected = add_accounts([f"Участник {i}" for i in range(503)])
    path = f"/api/v1/admin/rounds/{round_id}/participants"
    page = api.get(path, headers=admin, params={"limit": 100}).json()
    seen = [r["id"] for r in page["rows"]]
    assert page["next_cursor"] == seen[-1]
    with ThreadPoolExecutor(1) as pool:
        registration = pool.submit(
            api.post,
            "/api/v1/auth/register",
            json={
                "email": "concurrent@example.com",
                "password": "registration12345",
                "display_name": "Параллельная регистрация",
            },
        )
        # Fetch a page while the new account is being committed.
        page = api.get(
            path,
            headers=admin,
            params={
                "limit": 100,
                "cursor": page["next_cursor"],
            },
        ).json()
        seen.extend(r["id"] for r in page["rows"])
        created = registration.result(timeout=15)
        assert created.status_code == 201
        expected.append(created.json()["id"])
    while page["next_cursor"] is not None:
        page = api.get(
            path,
            headers=admin,
            params={
                "limit": 100,
                "cursor": page["next_cursor"],
            },
        ).json()
        seen.extend(r["id"] for r in page["rows"])
    assert seen == sorted(expected)
    assert len(seen) == len(set(seen)) == 504


@pytest.mark.parametrize(
    "query,expected",
    [
        ("%", ["Сто%"]),
        ("_", ["Имя_"]),
        ("\\", ["Слэш\\"]),
        ("ёлка", ["Ёлка"]),
    ],
)
def test_search_treats_wildcards_literally(api, admin, round_id, query, expected):
    add_accounts(["Сто%", "Имя_", "Слэш\\", "Ёлка", "Обычный"])
    response = api.get(
        f"/api/v1/admin/rounds/{round_id}/participants",
        headers=admin,
        params={"query": query},
    )
    assert response.status_code == 200
    assert [r["display_name"] for r in response.json()["rows"]] == expected


def test_current_round_scenario_filter_includes_draft_without_exposing_it(
    api,
    request_api,
    admin,
    player,
    active_round,
    chain,
    command,
):
    add_accounts(["Без сценария"])
    request_api(
        "PUT", f"/rounds/{active_round}/scenario", player["headers"], command(chain())
    )
    response = api.get(
        f"/api/v1/admin/rounds/{active_round}/participants",
        headers=admin,
        params={"has_current_scenario": "true"},
    )
    assert response.status_code == 200
    assert [r["id"] for r in response.json()["rows"]] == [player["id"]]
    assert "steps" not in response.text
