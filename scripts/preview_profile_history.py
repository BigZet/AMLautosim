"""Stage-05 memory-only workbench: shared frozen context, isolated participants."""

from copy import deepcopy

from nicegui import ui
from pydantic import ValidationError

from tests.profile_history_support import profile_config
from tests.purchase_support import mixed_goal
from tests.counterparty_support import step
from src.aml_workshop_simulator.core.errors import ValidationFailed
from src.aml_workshop_simulator.schemas.round_config import parse_game_config
from src.aml_workshop_simulator.services.profile_history import history_summary
from src.aml_workshop_simulator.services.configuration import snapshot_specs
from src.aml_workshop_simulator.services.counterparties import canonical_expanded_steps
from src.aml_workshop_simulator.services.expanded_simulation import (
    evaluate_expanded_scenario,
)
from src.aml_workshop_simulator.services.projections import card_out
from src.aml_workshop_simulator.services.round_configuration import config_version
from src.aml_workshop_simulator.ui.nicegui.client import APIError
from src.aml_workshop_simulator.ui.nicegui.game import GameEditor
from src.aml_workshop_simulator.ui.nicegui.participant import (
    ParticipantScreen,
    scenario_resources,
    scenario_resource_tiles,
)
from src.aml_workshop_simulator.ui.nicegui.profile_history import (
    ProfileHistoryForm,
    profile_history_panel,
)


def main():
    draft = profile_config()
    round_data = None
    states = {}

    @ui.page("/admin")
    def admin_page():
        nonlocal round_data
        ui.label("Этап 05 — настройка профиля").classes("text-xl")
        ui.label("Изолированный стенд: данные только в памяти. Перезапуск очищает их.")
        if round_data:
            ui.label("Настройки зафиксированы после старта.")
            profile_history_panel(round_data)
            ui.link("Первый участник", "/player/first")
            ui.link("Второй участник", "/player/second")
            return
        form_box = ui.column().classes("w-full")
        status = ui.label("")

        def form():
            form_box.clear()
            with form_box:
                ProfileHistoryForm(
                    draft["behavior"], lambda: status.set_text("Изменения в черновике")
                )

        def select(e):
            if round_data:
                return
            draft["behavior"] = profile_config()["behavior"]
            if e.value == "unknown":
                draft["behavior"]["history"]["operations"] = None
            elif e.value == "empty":
                draft["behavior"]["history"]["operations"] = []
            form()

        ui.select(
            {
                "observed": "Сотрудник: пять наблюдаемых операций",
                "empty": "Сотрудник: операций не было",
                "unknown": "Сотрудник: история недоступна",
            },
            value="observed",
            label="Профиль и доступная история",
            on_change=select,
        )
        form()

        def start():
            nonlocal round_data
            if round_data:
                status.set_text("Раунд уже запущен; изменения запрещены.")
                return
            try:
                editable = deepcopy(draft)
                editable.pop("card_snapshots", None)
                model = parse_game_config(editable)
                config = model.dump()
                config["card_snapshots"] = deepcopy(draft["card_snapshots"])
                config["config_version"] = config_version(config)
                round_data = {
                    "id": 1,
                    "title": "Профиль и история — этап 05",
                    "status": "active",
                    "config_version": config["config_version"],
                    "game_config": config,
                    "context_summary": history_summary(model.behavior).model_dump(
                        mode="json"
                    ),
                }
            except (ValidationError, ValidationFailed) as error:
                status.set_text(str(error))
                return
            ui.navigate.to("/admin")

        ui.button("Зафиксировать и запустить стенд", on_click=start)

    @ui.page("/player/{participant}")
    async def participant_page(participant: str):
        if not round_data:
            ui.label("Ожидаем начала стенда")
            ui.link("Настроить профиль", "/admin")
            return
        config = round_data["game_config"]
        cards = [
            card_out(s, schema_version=8).model_dump(mode="json")
            for s in snapshot_specs(config).values()
        ]
        state = states.setdefault(
            participant,
            {"round": deepcopy(round_data), "scenario": None, "can_edit": True},
        )

        class Transport:
            async def request(self, method, path, **kwargs):
                if method == "GET":
                    return deepcopy(cards if path.endswith("/cards") else state)
                try:
                    values = canonical_expanded_steps(kwargs["body"]["steps"], config)
                    snapshot = evaluate_expanded_scenario(values, config)
                except (ValidationError, ValidationFailed) as error:
                    raise APIError(str(error), status=422) from error
                saved = {
                    "steps": values,
                    "resources": snapshot,
                    "revision": kwargs["body"]["expected_revision"] + 1,
                    "status": "editing",
                }
                state["scenario"] = saved
                return deepcopy(saved)

        ui.label(f"Участник: {participant}").classes("text-xl")
        profile_history_panel(state["round"])
        screen = ParticipantScreen.__new__(ParticipantScreen)
        screen.submitting = False
        screen.editor = GameEditor(Transport(), participant, {}, lambda: None)
        screen.changed = screen.editor.changed
        await screen.editor.poll()
        if state["scenario"] is None:
            screen.editor.steps.append(step(config, "card_transfer"))
            screen.editor.changed()
        screen.chain_box = ui.column().classes("w-full")
        box = ui.column().classes("w-full")
        status = ui.label("")

        def show():
            screen.render_chain()
            box.clear()
            with box:
                saved = state["scenario"]
                if saved:
                    scenario_resources(saved["resources"])
                    scenario_resource_tiles(saved["resources"])

        async def save():
            if not screen.editor.dirty:
                return
            try:
                await screen.editor.write()
            except APIError as error:
                status.set_text(str(error))
                return
            status.set_text("Сохранено на стенде")
            show()

        def goal():
            screen.editor.record["steps"] = mixed_goal(config)
            screen.editor.changed()
            show()

        ui.button("Загрузить цепочку цели с покупкой", on_click=goal)
        ui.button(
            "Добавить покупку",
            on_click=lambda: screen.add(
                next(c for c in cards if c["code"] == "purchase")
            ),
        )
        await save()
        show()
        ui.timer(0.8, save)

    ui.run(
        host="127.0.0.1",
        port=58186,
        show=False,
        reload=False,
        title="Профиль и предыстория — этап 05",
    )


if __name__ == "__main__":
    main()
