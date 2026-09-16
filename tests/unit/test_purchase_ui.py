import asyncio
from copy import deepcopy
from types import SimpleNamespace

from tests.purchase_support import purchase_config
from tests.counterparty_support import step
from src.aml_workshop_simulator.services.configuration import snapshot_specs
from src.aml_workshop_simulator.services.projections import card_out
from src.aml_workshop_simulator.services.expanded_simulation import (
    evaluate_expanded_scenario,
)


def test_purchase_form_and_both_turnover_labels(tmp_path, monkeypatch):
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation
    from src.aml_workshop_simulator.ui.nicegui.participant import (
        ParticipantScreen,
        scenario_resources,
        submission_conditions,
        resources,
        scoring_wait_panel,
    )

    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    config = purchase_config()
    cards = [
        card_out(s, schema_version=8).model_dump(mode="json")
        for s in snapshot_specs(config).values()
    ]
    screen = ParticipantScreen.__new__(ParticipantScreen)
    screen.submitting = False
    screen.open_steps = set()
    screen.editor = SimpleNamespace(
        editable=True,
        steps=[step(config, "card_transfer")],
        cards=cards,
        state={"round": {"game_config": config}},
    )
    screen.changed = lambda: None

    async def run():
        async with user_simulation() as user:

            @ui.page("/purchase-ui")
            def page():
                screen.chain_box = ui.column()
                screen.open_steps = {s["step_id"] for s in screen.editor.steps}
                screen.render_chain()

            await user.open("/purchase-ui")
            with user:
                screen.add(next(c for c in cards if c["code"] == "purchase"))
            await user.should_see("Покупка не засчитывается в цель")
            merchants = [
                c for c in user.find(ui.select).elements if "shop" in c.options
            ]
            assert len(merchants) == 1 and set(merchants[0].options) == {"shop"}
            with user:
                merchants[0].set_value("shop")
            values = deepcopy(screen.editor.steps)
            snapshot = evaluate_expanded_scenario(values, config)
            with user:
                scenario_resources(snapshot)
                submission_conditions(
                    {"resources": snapshot, "blockers": [], "can_submit": False}
                )
                resources(snapshot)
                scoring_wait_panel(
                    {
                        "round": {"status": "closed"},
                        "scenario": {"resources": snapshot, "steps": values},
                    },
                    cards,
                )
            await user.should_see("Всего потрачено (без комиссий): 11 000,00 ₽")
            await user.should_see("Засчитано в цель: 10 000,00 ₽")
            await user.should_see("Ещё 390 000,00 ₽")
            await user.should_see("Категория: Продукты")

    asyncio.run(run())
