"""Editor concurrency, lost responses and safe round changes against PostgreSQL."""

import asyncio
from copy import deepcopy

import httpx
import pytest

from src.aml_workshop_simulator.ui.nicegui.client import APIClient, APIError
from src.aml_workshop_simulator.ui.nicegui.game import GameEditor


def test_editor_conflict_and_submit_without_lost_updates(
    api, player, active_round, chain
):
    async def run():
        client = APIClient("http://test/api/v1", transport=httpx.ASGITransport(api.app))
        token = player["headers"]["X-Session-ID"]
        first = GameEditor(client, token, {}, lambda: None)
        second = GameEditor(client, token, {}, lambda: None)
        try:
            await first.poll()
            await second.poll()
            first.record["steps"] = chain(1)
            first.changed()
            await first.write()
            second.record["steps"] = chain(2)
            second.changed()
            await second.poll()
            assert second.conflict and len(second.steps) == 2
            second.accept_server(keep_local=True)
            await second.write()
            await first.poll()
            assert first.steps == second.steps
            first.record["steps"] = chain()
            first.changed()
            await first.evaluate()
            assert first.can_submit
            await first.write(submit=True)
            await second.poll()
            assert not second.editable
            assert second.state["scenario"]["status"] == "submitted"
        finally:
            await client.close()

    asyncio.run(run())


def test_lost_response_replays_original_command_and_preserves_new_input(
    api, player, active_round, chain
):
    async def run():
        base = httpx.ASGITransport(api.app)
        writes = []
        drop = True

        async def route(request):
            nonlocal drop
            response = await base.handle_async_request(request)
            await response.aread()
            if request.method == "PUT":
                writes.append(request.content)
                if drop:
                    drop = False
                    raise httpx.ReadTimeout("lost response", request=request)
            return response

        client = APIClient("http://test/api/v1", transport=httpx.MockTransport(route))
        editor = GameEditor(client, player["headers"]["X-Session-ID"], {}, lambda: None)
        try:
            await editor.poll()
            editor.record["steps"] = chain(1)
            editor.changed()
            with pytest.raises(APIError):
                await editor.write()
            assert editor.record["pending"]
            pending = deepcopy(editor.record["pending"])
            editor.record["steps"] = chain(2)
            editor.changed()
            await editor.poll()
            assert not editor.conflict
            await editor.write()
            assert writes[0] == writes[1]
            assert pending["body"]["expected_revision"] == 0
            assert editor.dirty and len(editor.steps) == 2
            await editor.write()
            assert not editor.dirty and editor.record["revision"] == 2
        finally:
            await client.close()

    asyncio.run(run())


def test_restart_discards_old_pending_commands(api, player, admin, active_round, chain):
    async def run():
        client = APIClient("http://test/api/v1", transport=httpx.ASGITransport(api.app))
        editor = GameEditor(client, player["headers"]["X-Session-ID"], {}, lambda: None)
        try:
            await editor.poll()
            editor.record.update(
                steps=chain(1),
                dirty=True,
                pending={
                    "method": "PUT",
                    "path": f"rounds/{active_round}/scenario",
                    "body": {},
                },
            )
            fresh = await client.request(
                "POST",
                f"admin/rounds/{active_round}/restart",
                session_id=admin["X-Session-ID"],
            )
            await editor.poll()
            assert editor.record["key"][0] == fresh["id"]
            assert editor.steps == [] and not editor.record.get("pending")
            assert not editor.editable
        finally:
            await client.close()

    asyncio.run(run())


def test_poll_started_before_save_cannot_restore_old_steps(
    api, player, active_round, chain
):
    async def run():
        backend = httpx.ASGITransport(api.app)
        captured, release = asyncio.Event(), asyncio.Event()
        delay = False

        async def route(request):
            response = await backend.handle_async_request(request)
            await response.aread()
            if delay and request.url.path.endswith("/rounds/current/state"):
                captured.set()
                await release.wait()
            return response

        client = APIClient("http://test/api/v1", transport=httpx.MockTransport(route))
        editor = GameEditor(client, player["headers"]["X-Session-ID"], {}, lambda: None)
        try:
            await editor.poll()
            editor.record["steps"] = chain(1)
            editor.changed()
            await editor.write()
            delay = True
            pending = asyncio.create_task(editor.poll())
            await captured.wait()
            editor.steps[0]["amount"] = "15000.01"
            editor.changed()
            await editor.write()
            revision = editor.record["revision"]
            release.set()
            await pending
            assert editor.steps[0]["amount"] == "15000.01"
            assert editor.record["revision"] == revision
            assert not editor.conflict
        finally:
            release.set()
            await client.close()

    asyncio.run(run())
