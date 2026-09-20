"""Mounted editor fields plus save/reload via an isolated canonicalizing transport."""

import asyncio
from copy import deepcopy

from tests.counterparty_support import config_v8
from src.aml_workshop_simulator.services.configuration import snapshot_specs
from src.aml_workshop_simulator.services.counterparties import canonical_expanded_steps
from src.aml_workshop_simulator.services.projections import card_out
from src.aml_workshop_simulator.ui.nicegui.game import GameEditor


def test_select_save_reload_change_party_and_admin_details(tmp_path, monkeypatch):
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation
    from src.aml_workshop_simulator.ui.nicegui.participant import ParticipantScreen
    from src.aml_workshop_simulator.ui.nicegui.counterparties import party_readonly

    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    config = config_v8()
    cards = [
        card_out(s).model_dump(mode="json") for s in snapshot_specs(config).values()
    ]
    state = {
        "round": {"id": 1, "config_version": "stage02-test", "game_config": config},
        "can_edit": True,
        "scenario": None,
    }

    class Transport:
        async def request(self, method, path, **kwargs):
            if method == "GET":
                return deepcopy(cards if path.endswith("/cards") else state)
            assert method == "PUT"
            body = kwargs["body"]
            saved = {
                "steps": canonical_expanded_steps(body["steps"], config),
                "revision": body["expected_revision"] + 1,
                "status": "editing",
            }
            state["scenario"] = saved
            return deepcopy(saved)

    screen = ParticipantScreen.__new__(ParticipantScreen)
    screen.submitting = False
    screen.open_steps = set()
    screen.editor = GameEditor(Transport(), "test", {}, lambda: None)
    screen.changed = screen.editor.changed

    async def run():
        await screen.editor.poll()
        async with user_simulation() as user:

            @ui.page("/stage02-ui")
            def page():
                screen.chain_box = ui.column()
                screen.open_steps = {s["step_id"] for s in screen.editor.steps}
                screen.render_chain()

            await user.open("/stage02-ui")
            with user:
                screen.add(next(c for c in cards if c["code"] == "incoming_transfer"))
                screen.add(next(c for c in cards if c["code"] == "card_transfer"))
            selectors = sorted(user.find(ui.select).elements, key=lambda e: e.id)
            parties = [s for s in selectors if "A" in s.options]
            assert len(parties) == 2
            assert all("shop" not in s.options for s in parties)
            assert all(s.value == "A" for s in parties)
            assert not any(
                "regular_sender" in s.options or "anonymous_wallet" in s.options
                for s in selectors
            )
            with user:
                for control in parties:
                    control.set_value("A")
            assert await screen.editor.write()
            # Restore solely from server state, with a fresh editor/local workspace.
            screen.editor = GameEditor(Transport(), "test", {}, lambda: None)
            screen.changed = screen.editor.changed
            await screen.editor.poll()
            await user.open("/stage02-ui")
            parties = sorted(
                (s for s in user.find(ui.select).elements if "A" in s.options),
                key=lambda e: e.id,
            )
            assert [s.value for s in parties] == ["A", "A"]
            with user:
                parties[0].set_value("B")
            assert await screen.editor.write()
            assert state["scenario"]["steps"][1]["recipient_id"] == "B"
            assert parties[0].value == "B"
            with user:
                party_readonly(config, state["scenario"]["steps"][1])
            await user.should_see("Получатель: Борис")
            assert "sender_relationship" not in screen.editor.steps[0]["action_details"]

    asyncio.run(run())
