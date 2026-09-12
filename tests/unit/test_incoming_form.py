"""Exercise the current NiceGUI forms against backend card projections."""

import asyncio
import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def isolated_ui_storage(tmp_path, monkeypatch):
    from nicegui.storage import Storage

    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    monkeypatch.setenv("NICEGUI_STORAGE_PATH", str(tmp_path / "nicegui"))


def projected_catalog():
    from src.aml_workshop_simulator.core.game_config import base_game_config
    from src.aml_workshop_simulator.domain.catalog import CARD_CATALOG
    from src.aml_workshop_simulator.domain.game_models import card_spec_from_catalog
    from src.aml_workshop_simulator.domain.round_policy import RoundPolicy
    from src.aml_workshop_simulator.services.projections import card_out

    specs = [card_spec_from_catalog(c, i) for i, c in enumerate(CARD_CATALOG, 1)]
    config = base_game_config()
    config["card_snapshots"] = json.loads(
        json.dumps([asdict(s) for s in specs], default=str)
    )
    policy = RoundPolicy.from_config(config, {s.key: s for s in specs})
    return config, [
        card_out(s, policy.for_card(s.key)).model_dump(mode="json") for s in specs
    ]


def test_incoming_form_exposes_sources_and_sender_without_legacy_frequency():
    from nicegui import ui
    from nicegui.testing.user_simulation import user_simulation

    from src.aml_workshop_simulator.schemas.scenarios import ScenarioStepIn
    from src.aml_workshop_simulator.ui.nicegui.participant import ParticipantScreen

    config, catalog = projected_catalog()
    incoming = next(c for c in catalog if c["code"] == "incoming_transfer")
    screen = ParticipantScreen.__new__(ParticipantScreen)
    screen.editor = SimpleNamespace(
        editable=True, steps=[], cards=catalog, state={"round": {"game_config": config}}
    )
    screen.submitting = False
    screen.changed = lambda: None

    async def run():
        async with user_simulation() as user:

            @ui.page("/test-incoming")
            def page():
                screen.chain_box = ui.column()
                screen.add(incoming)

            await user.open("/test-incoming")
            inputs = list(user.find(ui.number).elements)
            selects = list(user.find(ui.select).elements)
            assert len(inputs) == 1
            assert len(selects) == 5
            await user.should_not_see(ui.switch)
            source = next(s for s in selects if "crypto_exchange" in s.options)
            sender = next(
                s for s in selects if "anonymous_established_account" in s.options
            )
            assert source.options["crypto_exchange"] == "Криптобиржа"
            assert "Кыргызстан" in source.options["foreign_bank_kg"]
            with user:
                source.set_value("foreign_bank_kg")
                sender.set_value("anonymous_established_account")
                inputs[0].set_value(80000)
            step = screen.editor.steps[0]
            ScenarioStepIn.model_validate(step)
            assert step["action_details"] == {
                "transfer_source": "foreign_bank_kg",
                "sender_relationship": "anonymous_established_account",
            }
            assert step["amount"] == "80000"
            assert step["context"] == {
                "channel": "bank",
                "time_of_day": "day",
                "velocity": "normal",
            }
            assert "frequency" not in step

    asyncio.run(run())


def test_admin_editor_handles_new_frozen_card_and_current_occurrence_limit():
    from nicegui import ui
    from nicegui.testing.user_simulation import user_simulation

    from src.aml_workshop_simulator.schemas.round_config import GameConfigIn
    from src.aml_workshop_simulator.services.editor_metadata import editor_metadata
    from src.aml_workshop_simulator.ui.nicegui.configuration import ConfigForm

    config, catalog = projected_catalog()
    metadata = editor_metadata().model_dump(mode="json")
    assert all(
        len(card["visible_params"])
        == bool(card["channels"]) + len(card["fields"]) + len(card["context_fields"])
        for card in catalog
    )
    forms = []

    async def run():
        async with user_simulation() as user:

            @ui.page("/test-config")
            def page():
                forms.append(ConfigForm(config, catalog, metadata, lambda: None))

            await user.open("/test-config")
            edited = forms[0].config
            GameConfigIn.model_validate(edited)
            incoming = next(
                o for o in edited["operations"] if o["code"] == "incoming_transfer"
            )
            card = next(c for c in catalog if c["code"] == "incoming_transfer")
            assert incoming.get("max_occurrences", card["max_occurrences"]) == 3
            assert incoming["visible_params"] == [
                "channel",
                "context.velocity",
                "action.sender_relationship",
                "action.transfer_source",
                "context.time_of_day",
            ]
            assert (
                incoming.get("defaults", {}).get("channel", card["channels"][0])
                == "bank"
            )
            assert "show_frequency" not in incoming
            assert "card_snapshots" not in edited
            assert "config_version" not in edited
            switches = sorted(
                (
                    e
                    for e in user.find(ui.switch).elements
                    if e.text == "Максимум использований"
                ),
                key=lambda e: e.id,
            )
            index = next(
                i for i, c in enumerate(catalog) if c["code"] == "incoming_transfer"
            )
            with user:
                switches[index].set_value(True)
            assert incoming["max_occurrences"] == 3
            GameConfigIn.model_validate(edited)

    asyncio.run(run())


def test_exceeded_limit_does_not_show_a_green_check():
    from nicegui import ui
    from nicegui.testing.user_simulation import user_simulation

    from src.aml_workshop_simulator.ui.nicegui.participant import submission_conditions

    async def run():
        async with user_simulation() as user:

            @ui.page("/test-exceeded-limit")
            def page():
                submission_conditions(
                    {
                        "resources": {
                            "objective": {"target_outflow": "10000", "reached": False},
                            "totals": {"gross_outflow": "0"},
                            "limits": [
                                {
                                    "code": "night_operations",
                                    "label": "Ночные операции",
                                    "used": "3",
                                    "limit": "2",
                                    "remaining": "0",
                                    "kind": "count",
                                }
                            ],
                            "per_step": [{}],
                        },
                        "can_submit": False,
                        "blockers": [],
                    }
                )

            await user.open("/test-exceeded-limit")
            label = next(iter(user.find("Ночные операции").elements))
            assert "condition-pending" in label.parent_slot.parent.classes
            assert "condition-ok" not in label.parent_slot.parent.classes

    asyncio.run(run())
