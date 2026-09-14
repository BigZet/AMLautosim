"""Local stage-02 UI workbench. Run with python -m scripts.preview_counterparties.

Uses the real editor and normalizer with an in-memory transport. No database,
resource calculation, live API or production availability switch is involved.
"""

from copy import deepcopy

from nicegui import ui

from src.aml_workshop_simulator.core.errors import ValidationFailed
from src.aml_workshop_simulator.ui.nicegui.client import APIError

from tests.counterparty_support import config_v8, step
from src.aml_workshop_simulator.services.configuration import snapshot_specs
from src.aml_workshop_simulator.services.counterparties import canonical_expanded_steps
from src.aml_workshop_simulator.services.projections import card_out
from src.aml_workshop_simulator.ui.nicegui.counterparties import party_readonly
from src.aml_workshop_simulator.ui.nicegui.game import GameEditor
from src.aml_workshop_simulator.ui.nicegui.participant import ParticipantScreen


def main(*, timeline_mode=False):
    from src.aml_workshop_simulator.services.expanded_simulation import (
        evaluate_expanded_scenario,
    )
    from src.aml_workshop_simulator.ui.nicegui.operation_timeline import (
        timeline_summary,
    )

    config = config_v8()
    if timeline_mode:
        config["behavior"]["timeline"]["starts_at"] = "2026-09-13T23:30:00+03:00"
    cards = [
        card_out(s).model_dump(mode="json") for s in snapshot_specs(config).values()
    ]
    states = {}

    @ui.page("/{participant}")
    async def page(participant: str):
        state = states.setdefault(
            participant,
            {
                "round": {
                    "id": 1,
                    "config_version": "stage02-workbench",
                    "game_config": config,
                },
                "can_edit": True,
                "scenario": None,
            },
        )

        if timeline_mode and state["scenario"] is None:
            canonical = canonical_expanded_steps(
                [
                    step(config),
                    step(config, "card_transfer"),
                    step(config, "cash_withdrawal", None),
                ],
                config,
            )
            state["scenario"] = {
                "steps": canonical,
                "revision": 1,
                "status": "editing",
                "resources": evaluate_expanded_scenario(canonical, config),
            }

        class Transport:
            async def request(self, method, path, **kwargs):
                if method == "GET":
                    return deepcopy(cards if path.endswith("/cards") else state)
                body = kwargs["body"]
                try:
                    normalized = canonical_expanded_steps(body["steps"], config)
                except ValidationFailed as error:
                    raise APIError(str(error), status=422) from error
                saved = {
                    "steps": normalized,
                    "revision": body["expected_revision"] + 1,
                    "status": "editing",
                }
                if timeline_mode:
                    saved["resources"] = evaluate_expanded_scenario(normalized, config)
                state["scenario"] = saved
                return deepcopy(saved)

        ui.label(
            "Этап 03 — временная шкала"
            if timeline_mode
            else "Этап 02 — изолированная проверка контрагентов"
        ).classes("text-xl")
        ui.label(
            "Сохранение в памяти стенда. Запуск игры отключён; ресурсы считает движок этапа 03."
            if timeline_mode
            else "Сохранение в памяти стенда. Расчёт ресурсов и запуск игры отключены."
        )
        ui.label(f"Тестовый участник: {participant}")
        status = ui.label("Ожидание выбора")
        screen = ParticipantScreen.__new__(ParticipantScreen)
        screen.submitting = False
        screen.editor = GameEditor(Transport(), participant, {}, lambda: None)
        screen.changed = screen.editor.changed
        await screen.editor.poll()
        screen.chain_box = ui.column().classes("w-full")
        if not screen.editor.steps:
            for code in ("incoming_transfer", "card_transfer"):
                screen.add(next(c for c in cards if c["code"] == code))
        else:
            screen.render_chain()
        ui.label("Административный просмотр сохранённых сторон").classes("text-lg")
        details = ui.column()

        def show_saved():
            for item in screen.editor.steps:
                party_readonly(config, item)
            if timeline_mode and state["scenario"]:
                resources = state["scenario"]["resources"]
                timeline_summary(resources)
                ui.label(
                    f"Осталось игрового времени: {resources['resources_after']['time']}"
                )

        async def save():
            if not screen.editor.dirty:
                return
            try:
                await screen.editor.write()
            except Exception as error:
                status.set_text(str(error))
                return
            status.set_text("Сохранено")
            details.clear()
            with details:
                show_saved()

        if state["scenario"]:
            status.set_text("Сохранено")
            with details:
                show_saved()
        ui.timer(0.8, save)
        ui.button("Сохранить", on_click=save)

    ui.run(
        host="127.0.0.1",
        port=58184 if timeline_mode else 58183,
        show=False,
        reload=False,
        title="Проверка контрагентов",
    )


if __name__ == "__main__":
    main()
