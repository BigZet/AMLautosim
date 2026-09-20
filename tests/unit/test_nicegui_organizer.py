"""Delayed organizer reads must not restore stale or signed-out content."""

import asyncio
from types import SimpleNamespace

import pytest

from src.aml_workshop_simulator.ui.nicegui.organizer import OrganizerScreen


@pytest.mark.parametrize("panel", ["participants", "results", "audit", "detail"])
@pytest.mark.parametrize("change", ["restart", "new_request", "logout"])
def test_delayed_panel_response_is_discarded(panel, change):
    async def run():
        # No mounted UI is needed: a stale read must return before touching it.
        screen = OrganizerScreen.__new__(OrganizerScreen)
        screen.round = {"id": 1}
        screen.token = "test-session"
        screen.storage = {"auth_admin": {"session_id": screen.token}}
        screen.read_versions = {}
        screen.query = SimpleNamespace(value="first search")
        screen.event_filter = SimpleNamespace(value="")
        entered, release = asyncio.Event(), asyncio.Event()

        async def request(*args, **kwargs):
            entered.set()
            await release.wait()
            return {}

        async def guarded(work):
            return await work()

        screen.request, screen.guarded = request, guarded
        call = (
            screen.detail(1, 1)
            if panel == "detail"
            else getattr(screen, f"load_{panel}")()
        )
        task = asyncio.create_task(call)
        await entered.wait()
        if change == "restart":
            screen.round = {"id": 2}
        elif change == "new_request":
            screen.begin_read(panel)
        else:
            screen.storage.clear()
        release.set()
        await task

    asyncio.run(run())


@pytest.mark.parametrize("finish", ["disconnect", "delete", "confirm", "cancel"])
def test_confirmation_client_lifecycle(finish):
    from nicegui import ui
    from nicegui.testing.user_simulation import user_simulation

    async def run():
        async with user_simulation() as user:
            @ui.page("/confirmation-test")
            def page():
                ui.label("Confirmation test")
            await user.open("/confirmation-test")
            screen = OrganizerScreen.__new__(OrganizerScreen)
            async def confirm():
                with user:
                    return await screen.confirm("Confirm action")
            task = asyncio.create_task(confirm())
            await asyncio.sleep(0.1)
            dialog = next(iter(user.find(ui.dialog).elements))
            client = dialog.client
            if finish == "disconnect":
                for handler in list(client.disconnect_handlers):
                    handler()
            elif finish == "delete":
                client.delete()
            else:
                dialog.submit(True if finish == "confirm" else None)
            result = await asyncio.wait_for(task, 2)
            assert result is (True if finish == "confirm" else None)
            assert not client.disconnect_handlers
            assert dialog.is_deleted

    asyncio.run(run())
