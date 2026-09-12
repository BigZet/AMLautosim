"""Transport failure and credential isolation tests without network access."""

import asyncio

import httpx
import pytest

from src.aml_workshop_simulator.ui.nicegui import auth
from src.aml_workshop_simulator.ui.nicegui.client import APIClient, APIError


def test_concurrent_requests_keep_credentials_separate():
    async def run():
        seen = []

        async def respond(request):
            await asyncio.sleep(0)
            seen.append(request.headers.get("X-Session-ID"))
            return httpx.Response(200, json={"ok": True})

        client = APIClient("http://test/api/v1", transport=httpx.MockTransport(respond))
        try:
            await asyncio.gather(
                *(
                    client.request("GET", "auth/session", session_id=t)
                    for t in ["first", "second", None]
                )
            )
            assert seen == ["first", "second", None]
            assert "X-Session-ID" not in client.http.headers
        finally:
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "response,expected",
    [
        (httpx.Response(502, text="<html>Bad gateway</html>"), "api_error"),
        (
            httpx.Response(
                429,
                headers={"Retry-After": "60", "X-Request-ID": "trace"},
                json={"code": "login_temporarily_locked", "message": "Подождите"},
            ),
            "login_temporarily_locked",
        ),
        (httpx.Response(200, text="broken"), "invalid_response"),
    ],
)
def test_errors(response, expected):
    async def run():
        client = APIClient(
            "http://test", transport=httpx.MockTransport(lambda _: response)
        )
        try:
            with pytest.raises(APIError) as caught:
                await client.request("GET", "test")
            assert caught.value.code == expected
            if response.status_code == 429:
                assert caught.value.retry_after == 60
                assert caught.value.request_id == "trace"
        finally:
            await client.close()

    asyncio.run(run())


def test_transport_failure_does_not_logout():
    async def run():
        def fail(request):
            raise httpx.ConnectError("offline", request=request)

        client = APIClient("http://test", transport=httpx.MockTransport(fail))
        storage = {"auth_play": {"session_id": "keep-me"}}
        try:
            with pytest.raises(APIError):
                await auth.verify(client, storage, "play")
            assert auth.credential(storage, "play") == "keep-me"
        finally:
            await client.close()

    asyncio.run(run())


def test_late_login_cannot_restore_logged_out_session():
    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        revoked = []

        async def respond(request):
            if request.method == "POST":
                started.set()
                await release.wait()
                return httpx.Response(
                    200,
                    json={
                        "session_id": "late",
                        "expires_at": "2026-09-13T00:00:00Z",
                        "audience": "play",
                        "user": {"id": 1, "role": "participant", "display_name": "A"},
                    },
                )
            revoked.append(request.headers.get("X-Session-ID"))
            return httpx.Response(204)

        client = APIClient("http://test", transport=httpx.MockTransport(respond))
        storage = {}
        try:
            pending = asyncio.create_task(
                auth.login(client, storage, "play", "a@example.com", "password123")
            )
            await started.wait()
            await auth.logout(client, storage, "play")
            release.set()
            assert not await pending
            assert auth.credential(storage, "play") is None
            assert revoked == ["late"]
        finally:
            await client.close()

    asyncio.run(run())
