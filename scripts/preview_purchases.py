"""Stage-04 local workbench: real calculations, memory-only transport, no DB."""

from copy import deepcopy

from nicegui import ui

from tests.purchase_support import purchase_config, mixed_goal
from tests.counterparty_support import step
from src.aml_workshop_simulator.core.errors import ValidationFailed
from src.aml_workshop_simulator.services.configuration import snapshot_specs
from src.aml_workshop_simulator.services.counterparties import canonical_expanded_steps
from src.aml_workshop_simulator.services.expanded_simulation import (
    evaluate_expanded_scenario,
    score_expanded_scenario,
)
from src.aml_workshop_simulator.services.projections import card_out
from src.aml_workshop_simulator.domain.simulation import submit_blockers
from src.aml_workshop_simulator.ui.nicegui.client import APIError
from src.aml_workshop_simulator.ui.nicegui.game import GameEditor
from src.aml_workshop_simulator.ui.nicegui.participant import (
    ParticipantScreen,
    scenario_resources,
    scenario_resource_tiles,
    submission_conditions,
)


def main():
    config = purchase_config()
    cards = [
        card_out(s, schema_version=8).model_dump(mode="json")
        for s in snapshot_specs(config).values()
    ]
    states = {}

    @ui.page("/{participant}")
    async def page(participant: str):
        state = states.setdefault(
            participant,
            {
                "round": {
                    "id": 1,
                    "config_version": "stage04-workbench",
                    "game_config": config,
                },
                "scenario": None,
                "can_edit": True,
            },
        )

        class Transport:
            async def request(self, method, path, **kwargs):
                if method == "GET":
                    return deepcopy(cards if path.endswith("/cards") else state)
                try:
                    values = canonical_expanded_steps(kwargs["body"]["steps"], config)
                    snapshot = evaluate_expanded_scenario(values, config)
                except ValidationFailed as error:
                    raise APIError(str(error), status=422) from error
                blockers = submit_blockers(snapshot)
                if path.endswith("/preview"):
                    return {
                        "resources": snapshot,
                        "blockers": blockers,
                        "can_submit": not blockers,
                    }
                if path.endswith("/submit") and blockers:
                    raise APIError(
                        blockers[0]["message"],
                        status=422,
                        details={"violations": blockers},
                    )
                submitted = path.endswith("/submit")
                saved = {
                    "steps": values,
                    "resources": snapshot,
                    "revision": kwargs["body"]["expected_revision"] + 1,
                    "status": "submitted" if submitted else "editing",
                }
                state.update(scenario=saved, can_edit=not submitted)
                return deepcopy(saved)

        ui.label("Этап 04 — покупки и целевой оборот").classes("text-xl")
        ui.label(
            "Локальный стенд. Расчёт настоящий; данные в памяти, без БД. Это ещё не полный игровой режим."
        )
        status = ui.label("")
        screen = ParticipantScreen.__new__(ParticipantScreen)
        screen.submitting = False
        screen.editor = GameEditor(Transport(), participant, {}, lambda: None)
        screen.changed = screen.editor.changed
        await screen.editor.poll()
        if state["scenario"] is None:
            screen.editor.steps.append(step(config, "card_transfer"))
            screen.editor.changed()
        screen.chain_box = ui.column().classes("w-full")
        summary = ui.column().classes("w-full")

        def show():
            screen.render_chain()
            screen.chain_box.set_visibility(screen.editor.editable)
            summary.clear()
            saved = state["scenario"]
            if not saved:
                return
            snapshot = saved["resources"]
            with summary:
                scenario_resources(snapshot)
                scenario_resource_tiles(snapshot)
                submission_conditions(
                    {
                        "resources": snapshot,
                        "blockers": submit_blockers(snapshot),
                        "can_submit": screen.editor.editable and not submit_blockers(snapshot),
                    }
                )
                risk = score_expanded_scenario(saved["steps"], config)["risk_score"]
                ui.label(f"Учебный риск: {risk} · Статус: {saved['status']}")

        async def save():
            if not screen.editor.dirty:
                return
            try:
                await screen.editor.write()
            except APIError as error:
                status.set_text(str(error))
                return
            status.set_text("Сохранено")
            show()

        async def submit():
            await save()
            try:
                await screen.editor.write(submit=True)
            except APIError as error:
                status.set_text(str(error))
                return
            status.set_text("Сценарий принят на стенде")
            show()

        def load_goal():
            state.update(scenario=None, can_edit=True)
            screen.editor.state = deepcopy(state)
            screen.editor.record.update(
                steps=mixed_goal(config), revision=0, dirty=False
            )
            screen.editor.record.pop("pending", None)
            screen.editor.changed()
            show()

        with ui.row():
            ui.button(
                "Добавить покупку",
                on_click=lambda: screen.add(
                    next(c for c in cards if c["code"] == "purchase")
                ),
            )
            ui.button("Загрузить пример цели с покупкой", on_click=load_goal)
            ui.button("Отправить на стенде", on_click=submit)
        await save()
        show()
        ui.timer(0.8, save)

    ui.run(
        host="127.0.0.1",
        port=58185,
        show=False,
        reload=False,
        title="Покупки — этап 04",
    )


if __name__ == "__main__":
    main()
