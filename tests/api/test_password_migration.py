import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from passlib.hash import bcrypt_sha256
from sqlalchemy import select, update

from src.aml_workshop_simulator.db.models.users import User
from src.aml_workshop_simulator.db.session import AsyncSessionLocal
from src.aml_workshop_simulator.services import authentication


def test_legacy_rehash_only_after_success_and_serializes_logins(
    api, player, monkeypatch
):
    password = "Я🙂" * 64
    legacy = bcrypt_sha256.hash(password)

    async def stored(replace=False):
        async with AsyncSessionLocal() as db:
            if replace:
                await db.execute(
                    update(User)
                    .where(User.id == player["id"])
                    .values(hashed_password=legacy)
                )
                await db.commit()
            return (
                await db.execute(
                    select(User.hashed_password).where(User.id == player["id"])
                )
            ).scalar_one()

    assert asyncio.run(stored(True)) == legacy
    payload = {"email": player["email"], "password": "wrong-password"}
    assert api.post("/api/v1/auth/login", json=payload).status_code == 401
    assert asyncio.run(stored()) == legacy
    hashes = []
    original = authentication.get_password_hash

    def recorded(value):
        hashes.append(True)
        return original(value)

    monkeypatch.setattr(authentication, "get_password_hash", recorded)
    barrier = Barrier(2)

    def login():
        barrier.wait(timeout=10)
        return api.post("/api/v1/auth/login", json={**payload, "password": password})

    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: login(), range(2)))
    assert [r.status_code for r in responses] == [200, 200]
    assert asyncio.run(stored()).startswith("$argon2id$")
    assert len(hashes) == 1
    for response in responses:
        assert (
            api.get(
                "/api/v1/auth/session",
                headers={
                    "X-Session-ID": response.json()["session_id"],
                },
            ).status_code
            == 200
        )
