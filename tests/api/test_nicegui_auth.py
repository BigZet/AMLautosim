"""New async client and real authentication, against disposable PostgreSQL."""

import asyncio
from uuid import uuid4

import httpx
import pytest

from src.aml_workshop_simulator.ui.nicegui import auth
from src.aml_workshop_simulator.ui.nicegui.client import APIClient, APIError


def test_register_login_reload_logout_and_audiences(api):
    async def run():
        client = APIClient("http://test/api/v1", transport=httpx.ASGITransport(api.app))
        storage = {}
        email = f"{uuid4().hex}@example.com"
        try:
            user = await client.request(
                "POST",
                "auth/register",
                body={
                    "email": email,
                    "display_name": "Тест NiceGUI",
                    "password": "participant123",
                },
            )
            assert auth.credential(storage, "play") is None
            assert await auth.login(client, storage, "play", email, "participant123")
            participant_token = auth.credential(storage, "play")
            assert (await auth.verify(client, storage, "play")).id == user["id"]
            # Serialised storage survives a UI process restart.
            import json

            restored = json.loads(json.dumps(storage))
            assert (await auth.verify(client, restored, "play")).id == user["id"]
            with pytest.raises(APIError) as caught:
                await auth.login(client, storage, "admin", email, "participant123")
            assert caught.value.code == "forbidden"
            assert auth.credential(storage, "play") == participant_token
            assert await auth.login(
                client, storage, "admin", "admin@example.com", "admin12345"
            )
            await auth.logout(client, storage, "play")
            assert auth.credential(storage, "play") is None
            assert await auth.verify(client, storage, "admin") is not None
            with pytest.raises(APIError) as caught:
                await client.request(
                    "GET", "auth/session", session_id=participant_token
                )
            assert caught.value.code == "session_revoked"
        finally:
            await client.close()

    asyncio.run(run())


def test_blocking_clears_ui_session_and_requires_new_login(
    api, player, admin, round_id, request_api
):
    async def run():
        client = APIClient("http://test/api/v1", transport=httpx.ASGITransport(api.app))
        storage = {"auth_play": {"session_id": player["headers"]["X-Session-ID"]}}
        try:
            await client.request(
                "PUT",
                f"admin/rounds/{round_id}/participants/{player['id']}/access",
                session_id=admin["X-Session-ID"],
                body={
                    "blocked": True,
                    "reason": "Проверка NiceGUI",
                    "expected_access_revision": 1,
                },
            )
            with pytest.raises(APIError) as caught:
                await auth.verify(client, storage, "play")
            assert caught.value.code == "session_revoked"
            assert auth.credential(storage, "play") is None
        finally:
            await client.close()

    asyncio.run(run())
