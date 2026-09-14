import asyncio

from src.aml_workshop_simulator.ui.nicegui.configuration import configuration_violation
from src.aml_workshop_simulator.ui.nicegui.shap_result import number


def test_russian_error_fields_and_signed_values():
    assert (
        configuration_violation(
            {
                "field": "game_config.behavior.counterparties.2.name",
                "message": "Укажите имя",
            }
        )
        == "Сторона 3, название: Укажите имя"
    )
    assert (
        configuration_violation(
            {"field": "game_config.behavior", "message": "История вне окна"}
        )
        == "История вне окна"
    )
    assert number(-1.25, 2, True) == "-1,25"
    assert number(0.001, 6, True) == "+0,001000"


def test_financial_settings_are_readonly_and_old_risk_control_absent(
    tmp_path, monkeypatch
):
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation
    from scripts.check_expanded_balance import demo_config
    from src.aml_workshop_simulator.services.editor_metadata import editor_metadata
    from src.aml_workshop_simulator.ui.nicegui.configuration import ConfigForm

    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    config = demo_config()

    async def run():
        async with user_simulation() as user:

            @ui.page("/audit-form")
            def page():
                ConfigForm(
                    config, [], editor_metadata().model_dump(mode="json"), lambda: None
                )

            await user.open("/audit-form")
            await user.should_not_see("Базовый риск")
            await user.should_not_see("Переопределить стоимость и лимиты")
            inputs = [
                e for e in user.find(ui.input).elements if e.label == "Начальный баланс"
            ]
            assert len(inputs) == 1 and inputs[0]._props["readonly"]
            toggles = [
                e for e in user.find(ui.switch).elements if e.text == "Доступна в игре"
            ]
            assert len(toggles) == 5 and all(e._props["disable"] for e in toggles)

    asyncio.run(run())
