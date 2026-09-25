import asyncio
import json
from copy import deepcopy
from pathlib import Path
import pytest
from src.aml_workshop_simulator.core.errors import Conflict
from src.aml_workshop_simulator.services.game_classifier import get_game_classifier


def test_only_round_settings_are_mutable():
    model = get_game_classifier()
    base = deepcopy(model.context)
    for change in [
        lambda c: c["leaderboard"]["weights"].update(stealth="0.50", resources="0.50"),
        lambda c: c["operations"][0].update(fee_rate="0.10"),
        lambda c: c["behavior"]["timeline"].update(starts_at="2027-01-01T09:00:00+03:00"),
    ]:
        config = deepcopy(base)
        change(config)
        with pytest.raises((Conflict, ValueError)):
            model.check_config(config)
    with pytest.raises(Conflict):
        model.check_config({**base, "risk_model": {"model_sha256":"tampered"}}, require_pin=True)


def test_draft_form_edits_history_goal_and_limits(tmp_path, monkeypatch):
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation
    from src.aml_workshop_simulator.ui.nicegui.configuration import ConfigForm
    from src.aml_workshop_simulator.services.editor_metadata import editor_metadata
    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    model = get_game_classifier()
    forms = []
    changes = []
    async def run():
        async with user_simulation() as user:
            @ui.page("/settings-test")
            def page():
                forms.append(ConfigForm(model.context, model.context["card_snapshots"], editor_metadata().model_dump(mode="json"), lambda: changes.append(True)))
            await user.open("/settings-test")
            with user:
                for label, value in [("Цель исходящих операций", "250000"), ("Покупки за раунд", "45000"), ("Сумма в истории", "12345.67")]:
                    field = next(e for e in user.find(ui.input).elements if e.label == label)
                    assert not field.props.get("readonly")
                    field.set_value(value)
                history_toggle = next(e for e in user.find(ui.switch).elements if e.text == "История доступна")
                history_toggle.set_value(False)
            c = forms[0].config
            assert c["objectives"]["target_outflow"] == "250000"
            assert c["behavior"]["purchases"]["version"] == "purchase-policy-v2"
            assert c["behavior"]["aml_context"]["history_coverage"] == "unknown"
            model.check_config({**c, "card_snapshots": model.context["card_snapshots"]})
            with user:
                history_toggle.set_value(True)
            assert c["behavior"]["aml_context"]["history_coverage"] == "complete"
            model.check_config({**c, "card_snapshots": model.context["card_snapshots"]})
            assert changes
    asyncio.run(run())


def test_custom_purchase_limits_are_applied_and_reported():
    from src.aml_workshop_simulator.services.aml_context import evaluate
    model = get_game_classifier()
    config = deepcopy(model.context)
    config["behavior"]["purchases"].update(version="purchase-policy-v2", max_total="45000.00")
    for operation in config["operations"]:
        if operation["code"] == "purchase":
            operation.update(max_amount="40000.00", max_occurrences=5)
    rows = json.loads((Path(__file__).parents[1] / "fixtures/retired_limits_baseline.json").read_text())["rows"]
    step = deepcopy(next(s for row in rows for s in row["steps"] if s["card"]["code"] == "purchase"))
    step.update(amount="35000.00", interval_minutes=None)
    assert not evaluate([step], config)["violations"]
    second = deepcopy(step)
    second.update(step_id="12345678-1234-1234-1234-123456789abc", interval_minutes=1)
    violations = evaluate([step, second], config)["violations"]
    exceeded = next(v for v in violations if v["reason"] == "purchase_total_exceeded")
    assert exceeded["allowed"] == "45000.00"
    assert "45 000" in exceeded["message"]
    assert "30 000" not in exceeded["message"]


@pytest.mark.parametrize("limit", [2, 3, 5])
@pytest.mark.parametrize("extra", [0, 1])
def test_purchase_count_report_matches_effective_card(limit, extra):
    from uuid import uuid4
    from src.aml_workshop_simulator.services.aml_context import evaluate

    config = deepcopy(get_game_classifier().context)
    config["behavior"]["purchases"].update(version="purchase-policy-v2", max_total="45000.00")
    for operation in config["operations"]:
        if operation["code"] == "purchase":
            operation["max_occurrences"] = limit
    rows = json.loads((Path(__file__).parents[1] / "fixtures/retired_limits_baseline.json").read_bytes())["rows"]
    sample = next(s for row in rows for s in row["steps"] if s["card"]["code"] == "purchase")
    steps = [{**deepcopy(sample), "step_id": str(uuid4()), "amount": "1000.00", "interval_minutes": 1 if i else None} for i in range(limit + extra)]
    snapshot = evaluate(steps, config)
    report = next(row for row in snapshot["limits"] if row["code"] == "purchase_count")
    assert report["limit"] == str(limit)
    assert report["used"] == str(limit + extra)
    assert report["remaining"] == "0"
    violations = [row for row in snapshot["violations"] if row["reason"] == "max_occurrences_exceeded"]
    assert len(violations) == extra
    if extra:
        assert violations[0]["allowed"] == str(limit)
