import asyncio
from copy import deepcopy

import pytest


@pytest.mark.parametrize("admin", [False, True])
@pytest.mark.parametrize("kind", ["legacy_risk", "aml_probability"])
def test_mounted_board_preserves_saved_score_semantics(admin, kind, tmp_path, monkeypatch):
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation
    from src.aml_workshop_simulator.ui.nicegui.participant import board_table

    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    row = dict(rank=1, display_name="Player", participant_id=1, email="test@example.test",
               is_blocked=False, risk_score="10.00", stealth_score="90.00",
               game_score="76.00", resource_score="50.00", risk_label="normal",
               score_kind=kind, aml_probability=0.09999 if kind == "aml_probability" else None,
               category="low" if kind == "aml_probability" else None)
    saved = deepcopy(row)

    async def run():
        async with user_simulation() as user:
            @ui.page("/board-probability")
            def page():
                board_table({"rows": [row]}, admin=admin)

            await user.open("/board-probability")
            table = next(iter(user.find(ui.table).elements))
            visible = table.rows[0]
            if kind == "aml_probability":
                assert visible["risk_score"] == "10,0%"
                assert visible["risk_label"] == "Низкая вероятность"
                await user.should_see("Вероятность AML-сценария в учебной модели")
                assert "Риск модели ↓" not in [c["label"] for c in table.columns]
            else:
                assert visible["risk_score"] == "10,00"
                assert visible["risk_label"] == "Обычный"
                assert "Риск модели ↓" in [c["label"] for c in table.columns]
                await user.should_not_see("Вероятность AML-сценария в учебной модели")

    asyncio.run(run())
    assert row == saved


def test_board_dtos_preserve_probability_and_reject_contradictory_category():
    from pydantic import ValidationError
    from src.aml_workshop_simulator.schemas.leaderboard import LeaderboardRowOut, AdminLeaderboardRowOut

    row = dict(rank=1, display_name="Player", participant_id=1, email="test@example.test",
               scenario_id=1, is_blocked=False, risk_score="10.00", stealth_score="90.00",
               game_score="76.00", resource_score="50.00", risk_label="normal",
               score_kind="aml_probability", aml_probability=0.09999, category="low",
               leaderboard_version="leaderboard-aml-probability-v1")
    for model in (LeaderboardRowOut, AdminLeaderboardRowOut):
        parsed = model.model_validate(row).model_dump()
        assert parsed["aml_probability"] == 0.09999
        assert parsed["category"] == "low"
        with pytest.raises(ValidationError):
            model.model_validate({**row, "category": "review"})
