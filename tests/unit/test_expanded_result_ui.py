import asyncio

from scripts.check_expanded_balance import demo_config, demo_steps
from src.aml_workshop_simulator.services.expanded_simulation import (
    evaluate_expanded_scenario,
)


def test_result_preserves_counterparties_and_calendar_time(tmp_path, monkeypatch):
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation
    from src.aml_workshop_simulator.ui.nicegui.participant import result_panel

    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    config = demo_config()
    steps = demo_steps(config, "varied")
    from src.aml_workshop_simulator.services.model_scoring import get_model_scorer

    scorer = get_model_scorer()
    config["risk_model"] = scorer.identity.copy()
    result = {
        "explanation": scorer.score(steps, config)["explanation"],
        "scores": {
            "game_score": "50",
            "risk_score": "32",
            "resource_score": "20",
            "risk_label": "review",
        },
        "resources": evaluate_expanded_scenario(steps, config),
        "rank": 1,
    }

    async def run():
        async with user_simulation() as user:

            @ui.page("/expanded-result")
            def page():
                result_panel(
                    result,
                    selected_tab="operations",
                    round_config=config,
                    scenario_steps=steps,
                )

            await user.open("/expanded-result")
            await user.should_see("14.09.2026,")
            await user.should_see("Магазин")
            await user.should_see("Борис — известный новый контрагент")
            await user.should_see("Засчитано в цель: 400 000,00 ₽")

    asyncio.run(run())
