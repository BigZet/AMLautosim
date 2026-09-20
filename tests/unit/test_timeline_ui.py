import asyncio
from copy import deepcopy

from tests.counterparty_support import config_v8, step
from src.aml_workshop_simulator.services.configuration import snapshot_specs
from src.aml_workshop_simulator.services.projections import card_out
from src.aml_workshop_simulator.ui.nicegui.game import GameEditor
from src.aml_workshop_simulator.services.expanded_simulation import (
    evaluate_expanded_scenario,
)


def test_interval_reorder_delete_and_reload(tmp_path, monkeypatch):
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation
    from src.aml_workshop_simulator.ui.nicegui.participant import ParticipantScreen
    from src.aml_workshop_simulator.services.counterparties import (
        canonical_expanded_steps,
    )

    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    config = config_v8()
    config["behavior"]["timeline"]["starts_at"] = "2026-09-13T23:30:00+03:00"
    cards = [
        card_out(s, schema_version=8).model_dump(mode="json")
        for s in snapshot_specs(config).values()
    ]
    values = [
        step(config),
        step(config, "card_transfer"),
        step(config, "cash_withdrawal", None),
    ]
    state = {
        "round": {"id": 1, "config_version": "timeline-test", "game_config": config},
        "can_edit": True,
        "scenario": {"steps": values, "revision": 1, "status": "editing"},
    }

    class Transport:
        async def request(self, method, path, **kwargs):
            if method == "GET":
                return deepcopy(cards if path.endswith("/cards") else state)
            body = kwargs["body"]
            canonical = canonical_expanded_steps(body["steps"], config)
            state["scenario"] = {
                "steps": canonical,
                "resources": evaluate_expanded_scenario(canonical, config),
                "revision": body["expected_revision"] + 1,
                "status": "editing",
            }
            return deepcopy(state["scenario"])

    screen = ParticipantScreen.__new__(ParticipantScreen)
    screen.submitting = False
    screen.open_steps = set()
    screen.editor = GameEditor(Transport(), "test", {}, lambda: None)
    screen.changed = screen.editor.changed

    async def run():
        await screen.editor.poll()
        async with user_simulation() as user:

            @ui.page("/timeline-test")
            def page():
                screen.chain_box = ui.column()
                screen.open_steps = {s["step_id"] for s in screen.editor.steps}
                screen.render_chain()

            await user.open("/timeline-test")

            # A party change updates the matching heading without rebuilding the form.
            with user:
                party_fields = [e for e in user.find(ui.select).elements if e._props.get("label") in ("Получатель", "Отправитель")]
                for field in party_fields:
                    alternative = next((key for key in field.options if key != field.value), None)
                    if alternative is not None:
                        name = field.options[alternative]
                        field.set_value(alternative)
                        captions = [e.text for e in user.find(ui.label).elements if "operation-caption" in e.classes]
                        assert any(name in caption for caption in captions)
                assert not any(e.text.startswith(("Начало:", "Выполнение:")) for e in user.find(ui.label).elements)

            def intervals():
                return sorted(
                    (e for e in user.find(ui.select).elements if 1440 in e.options),
                    key=lambda e: e.id,
                )

            with user:
                intervals()[1].set_value(60)
            with user:
                intervals()[0].set_value(1440)
            await user.should_see("15.09.2026, 00:30")
            # Actions must work while every operation is collapsed.
            with user:
                screen.open_steps.clear()
                screen.render_chain()
                assert all(not e.value for e in user.find(ui.expansion).elements)
                copies = sorted(
                    (b for b in user.find(ui.button).elements if b._props.get("icon") == "content_copy"),
                    key=lambda b: b.id,
                )
                copies[0].mark("copy-collapsed")
            previous_count = len(screen.editor.steps)
            user.find("copy-collapsed").click()
            assert len(screen.editor.steps) == previous_count + 1
            assert not screen.open_steps
            with user:
                deletes = sorted(
                    (b for b in user.find(ui.button).elements if b._props.get("icon") == "delete_outline"),
                    key=lambda b: b.id,
                )
                deletes[0].mark("delete-copy")
            user.find("delete-copy").click()
            assert len(screen.editor.steps) == previous_count
            with user:
                buttons = sorted(
                    (
                        b
                        for b in user.find(ui.button).elements
                        if b._props.get("icon") == "arrow_upward"
                    ),
                    key=lambda b: b.id,
                )
                buttons[-1].mark("move-first")
            user.find("move-first").click()
            assert screen.editor.steps[0]["interval_minutes"] is None
            assert screen.editor.steps[1]["interval_minutes"] == 1
            with user:
                deletes = sorted(
                    (
                        b
                        for b in user.find(ui.button).elements
                        if b._props.get("icon") == "delete_outline"
                    ),
                    key=lambda b: b.id,
                )
                deletes[1].mark("remove-second")
            user.find("remove-second").click()
            assert await screen.editor.write()
            expected = deepcopy(screen.editor.steps)
            expected_resources = state["scenario"]["resources"]
            screen.editor = GameEditor(Transport(), "test", {}, lambda: None)
            screen.changed = screen.editor.changed
            await screen.editor.poll()
            await user.open("/timeline-test")
            assert screen.editor.steps == expected
            assert evaluate_expanded_scenario(expected, config) == expected_resources
            await user.should_see("14.09.2026, 23:30")

    asyncio.run(run())
