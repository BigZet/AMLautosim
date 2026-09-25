import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nicegui import ui
from nicegui.storage import Storage
from nicegui.testing.user_simulation import user_simulation

from src.aml_workshop_simulator.services.configuration import snapshot_specs
from src.aml_workshop_simulator.services.projections import card_out
from src.aml_workshop_simulator.ui.nicegui.participant import ParticipantScreen, display_operation_amount
from tests.counterparty_support import step
from tests.purchase_support import purchase_config


@pytest.mark.parametrize("value, expected", [
    ("10000.00", "10 000"), (10000.0, "10 000"),
    ("10000.5", "10 000,50"), (10000.01, "10 000,01"),
    ("0.00", "0"), ("0.50", "0,50"),
])
def test_operation_amount_format(value, expected):
    assert display_operation_amount(value) == expected


def test_amount_heading_updates_without_rebuilding_cards(tmp_path, monkeypatch):
    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    config = purchase_config()
    screen = ParticipantScreen.__new__(ParticipantScreen)
    screen.submitting = False
    screen.open_steps = set()
    screen.changed = Mock()
    screen.editor = SimpleNamespace(
        editable=True,
        steps=[step(config, code) for code in (
            "salary", "incoming_transfer", "card_transfer", "cash_withdrawal", "purchase",
        )],
        cards=[card_out(s, schema_version=8).model_dump(mode="json")
               for s in snapshot_specs(config).values()],
        state={"round": {"game_config": config}},
    )

    async def run():
        async with user_simulation() as user:
            @ui.page("/amount-headings")
            def page():
                screen.chain_box = ui.column()
                screen.open_steps = {s["step_id"] for s in screen.editor.steps}
                screen.render_chain()

            await user.open("/amount-headings")
            fields = sorted(user.find(ui.number).elements, key=lambda e: e.id)
            labels = sorted(
                (e for e in user.find(ui.label).elements if "operation-heading-amount" in e._classes),
                key=lambda e: e.id,
            )
            assert len(fields) == len(labels) == 5
            operations = dict(screen.operation_elements)
            screen.changed.reset_mock()
            for index, (field, label, current) in enumerate(zip(fields, labels, reversed(screen.editor.steps))):
                for value in (23456.78 + index, None, 0, 12345.67 + index):
                    before = [other.text for other in labels]
                    with user:
                        field.set_value(value)
                    expected = f"{display_operation_amount(value) if value is not None else '—'} ₽"
                    assert label.text == expected
                    assert current["amount"] == ("" if value is None else str(value))
                    assert operations[current["step_id"]].text.endswith(f" · {expected}")
                    assert all(other.text == before[j] for j, other in enumerate(labels) if j != index)
                    assert screen.operation_elements == operations
                    assert operations[current["step_id"]].value is True
            assert screen.changed.call_count == 20
            with user:
                screen.editor.steps.append(step(config, 'card_transfer'))
                screen.render_chain()
            assert all(screen.operation_elements[key] is value for key, value in operations.items())
            assert all(not field.is_deleted for field in fields)
            with user:
                screen.editor.steps.reverse()
                screen.render_chain()
            assert all(screen.operation_elements[key] is value for key, value in operations.items())
            removed = screen.editor.steps.pop()
            with user:
                screen.render_chain()
            assert screen.operation_elements.get(removed['step_id']) is None
            assert all(not value.is_deleted for key, value in operations.items() if key != removed['step_id'])
            # A fresh authoritative state can replace a card's values after reconnect.
            from copy import deepcopy
            refreshed = deepcopy(screen.editor.steps[0])
            refreshed['amount'] = '34567.89'
            screen.editor.steps[0] = refreshed
            unchanged = dict(screen.operation_elements)
            with user:
                screen.render_chain()
            card = screen.operation_elements[refreshed['step_id']]
            amount_field = next(e for e in card.descendants() if isinstance(e, ui.number))
            assert amount_field.value == 34567.89
            assert all(screen.operation_elements[key] is value for key, value in unchanged.items()
                       if key != refreshed['step_id'])

    asyncio.run(run())
