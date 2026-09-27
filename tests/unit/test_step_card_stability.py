"""Local edits retain mounted fields across canonical save responses."""

import asyncio
from copy import deepcopy

import pytest

from tests.aml_context_support import context_fixture
from src.aml_workshop_simulator.services.aml_context import canonical_steps
from src.aml_workshop_simulator.services.configuration import snapshot_specs
from src.aml_workshop_simulator.services.projections import card_out
from src.aml_workshop_simulator.ui.nicegui.game import GameEditor

pytestmark = pytest.mark.runtime


@pytest.mark.parametrize("field", ["interval", "purpose", "sender", "country", "amount"])
def test_saved_step_edits_keep_mounted_controls(tmp_path, monkeypatch, field):
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation
    from src.aml_workshop_simulator.ui.nicegui.participant import ParticipantScreen

    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    config, _ = context_fixture()
    cards = [
        card_out(spec, schema_version=10).model_dump(mode="json")
        for spec in snapshot_specs(config).values()
    ]

    class Transport:
        async def request(self, method, path, **kwargs):
            body = kwargs["body"]
            return {
                "steps": canonical_steps(body["steps"], config),
                "revision": body["expected_revision"] + 1,
                "status": "editing",
            }

    screen = ParticipantScreen.__new__(ParticipantScreen)
    screen.submitting = False
    screen.open_steps = set()
    screen.editor = GameEditor(Transport(), "test", {"key": [1, "test"]}, lambda: None)
    screen.editor.cards = cards
    screen.editor.state = {
        "round": {"id": 1, "game_config": config}, "can_edit": True,
    }
    screen.changed = screen.editor.changed

    async def run():
        async with user_simulation() as user:
            @ui.page("/stable-step")
            def page():
                screen.chain_box = ui.column()
                screen.add(next(c for c in cards if c["code"] == "incoming_transfer"))
                screen.add(next(c for c in cards if c["code"] == "incoming_transfer"))

            await user.open("/stable-step")
            step_id = screen.editor.steps[1]["step_id"]
            card = screen.step_cards[step_id]
            element = card.element
            timeline = card.timeline
            fields = tuple(card.fields.descendants())
            original_step = screen.editor.steps[1]
            assert await screen.editor.write()
            assert screen.editor.steps[1] is not original_step
            # The server normalizes money; this must not remount the card either.
            with user:
                screen.render_chain()
            assert card.element is element

            for _ in range(2):
                with user:
                    if field == "interval":
                        timeline.set_value(10 if timeline.value == 1 else 1)
                    elif field == "amount":
                        control = next(e for e in fields if getattr(e, "label", None) == "Сумма")
                        control.set_value(23456.78 if control.value != 23456.78 else 34567.89)
                    else:
                        label, choices = {
                            "purpose": ("Назначение операции", ("unknown", "shared_expense")),
                            "sender": ("Отправитель", ("B", "A")),
                            "country": ("Банк отправителя", ("KG", "RU")),
                        }[field]
                        control = next(e for e in fields if getattr(e, "label", None) == label)
                        control.set_value(choices[0] if control.value != choices[0] else choices[1])
                    screen.render_chain()
                assert card.element is element
                assert card.timeline is timeline
                assert tuple(card.fields.descendants()) == fields
                assert not any(e.is_deleted for e in fields)
                assert await screen.editor.write()

            # Reordering only changes the interval/heading, not the input widgets.
            with user:
                screen.editor.steps.reverse()
                screen.changed()
                screen.render_chain()
            assert card.element is element
            assert card.timeline is None
            with user:
                screen.editor.steps.reverse()
                screen.changed()
                screen.render_chain()
            assert card.element is element
            assert card.timeline.value == 1

            # A real external attribute change still has to reach the form.
            replacement = deepcopy(screen.editor.steps)
            replacement[1]["sender_id"] = "B"
            replacement[1]["amount"] = "45678.90"
            screen.editor.record["steps"] = replacement
            with user:
                screen.render_chain()
            assert card.element is not element
            assert element.is_deleted
            amount = next(e for e in card.fields.descendants() if getattr(e, "label", None) == "Сумма")
            assert amount.value == 45678.9

    asyncio.run(run())
