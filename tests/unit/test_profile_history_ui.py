import asyncio
from copy import deepcopy

from tests.profile_history_support import profile_config
from src.aml_workshop_simulator.schemas.expanded_contract import ExpandedBehavior
from src.aml_workshop_simulator.services.profile_history import history_summary


def test_public_context_and_draft_controls(tmp_path, monkeypatch):
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation
    from src.aml_workshop_simulator.ui.nicegui.profile_history import (
        ProfileHistoryForm,
        profile_history_panel,
    )

    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    config = profile_config()
    config["behavior"]["counterparties"].append(
        {
            **config["behavior"]["counterparties"][-1],
            "id": "other-shop",
            "name": "Другой магазин",
            "category": "clothing",
        }
    )
    config["behavior"]["history"]["operations"][3]["category"] = "groceries"
    changed = []

    async def run():
        async with user_simulation() as user:

            @ui.page("/history-ui")
            def page():
                profile_history_panel(
                    {
                        "game_config": config,
                        "context_summary": history_summary(
                            ExpandedBehavior.model_validate(config["behavior"])
                        ).model_dump(mode="json"),
                    }
                )
                ProfileHistoryForm(config["behavior"], lambda: changed.append(True))

            await user.open("/history-ui")
            await user.should_see("Наёмный сотрудник")
            await user.should_see("105 000,50 ₽")
            await user.should_see("18 500,25 ₽")
            await user.should_see(
                "до игры, не входит в цель"
            )
            with user:
                fields = [
                    e
                    for e in user.find(ui.textarea).elements
                    if e.label == "Роль клиента"
                ]
                fields[0].set_value("Самозанятый")
                merchants = [
                    e
                    for e in user.find(ui.select).elements
                    if "other-shop" in e.options
                ]
                merchants[0].set_value("other-shop")
            assert config["behavior"]["history"]["operations"][3]["category"] is None
            assert (
                history_summary(ExpandedBehavior.model_validate(config["behavior"]))
                .events[3]
                .category
                == "clothing"
            )
            assert config["behavior"]["profile"]["title"] == "Самозанятый" and changed
            original = deepcopy(config)
            for events, message in [
                (None, "История недоступна. Отсутствие операций не установлено."),
                ([], "За наблюдаемый период операций не было."),
            ]:
                other = deepcopy(original)
                other["behavior"]["history"]["operations"] = events
                with user:
                    profile_history_panel(
                        {
                            "game_config": other,
                            "context_summary": history_summary(
                                ExpandedBehavior.model_validate(other["behavior"])
                            ).model_dump(mode="json"),
                        }
                    )
                await user.should_see(message)

    asyncio.run(run())


def test_config_form_keeps_expanded_contract(tmp_path, monkeypatch):
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation
    from src.aml_workshop_simulator.services.editor_metadata import editor_metadata
    from src.aml_workshop_simulator.ui.nicegui.configuration import ConfigForm

    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    config = profile_config()

    async def run():
        async with user_simulation() as user:
            forms = []

            @ui.page("/expanded-config-form")
            def page():
                forms.append(
                    ConfigForm(
                        config,
                        [],
                        editor_metadata().model_dump(mode="json"),
                        lambda: None,
                    )
                )

            await user.open("/expanded-config-form")
            await user.should_see("Роль клиента")
            assert forms[0].config["schema_version"] == 8
            assert forms[0].config["behavior"] == config["behavior"]

    asyncio.run(run())
