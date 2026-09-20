import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from nicegui import ui
from nicegui.testing.user_simulation import user_simulation

from src.aml_workshop_simulator.ui.nicegui.participant import (
    ParticipantScreen, submission_conditions,
)


def preview(step_id):
    return {
        "resources": {
            "objective": {"target_outflow": "100", "reached": False},
            "totals": {"gross_outflow": "0"},
            "limits": [], "per_step": [{}],
        },
        "can_submit": False,
        "blockers": [{
            "reason": "amount_out_of_range", "step_id": step_id,
            "field": "amount", "step_index": 2,
            "message": "Шаг 2 «Перевод»: сумма вне диапазона.",
        }],
    }


def test_error_button_opens_by_identity_and_targets_amount(monkeypatch):
    async def run():
        async with user_simulation() as user:
            screen = ParticipantScreen.__new__(ParticipantScreen)
            screen.editor = SimpleNamespace(editable=True)
            screen.submitting = False
            screen.open_steps = set()
            script = AsyncMock()
            monkeypatch.setattr(ui, "run_javascript", script)

            @ui.page("/correction-navigation")
            def page():
                # Deliberately render in reverse order: step identity wins over position.
                second = ui.expansion("Вторая операция", value=False)
                first = ui.expansion("Первая операция", value=False)
                screen.operation_elements = {"first": first, "second": second}
                submission_conditions(preview("second"), on_step=screen.focus_error_step)

            await user.open("/correction-navigation")
            user.find("Шаг 2").click()
            await user.should_see("Вторая операция")
            await asyncio.sleep(0)
            assert screen.operation_elements["second"].value is True
            assert screen.operation_elements["first"].value is False
            assert screen.open_steps == {"second"}
            script.assert_awaited_once()
            assert f'"c{screen.operation_elements["second"].id}"' in script.call_args.args[0]
            assert '"amount"' in script.call_args.args[0]
            script.reset_mock()
            screen.operation_elements.pop("second")
            await screen.focus_error_step("second", "amount")
            script.assert_not_called()

    asyncio.run(run())


def test_stale_or_global_errors_are_not_navigation_buttons():
    async def run():
        async with user_simulation() as user:
            @ui.page("/stale-correction")
            def page():
                submission_conditions(preview("second"), current=False, on_step=lambda *_: None)
                global_preview = preview(None)
                global_preview["blockers"][0]["message"] = "Общий лимит превышен"
                submission_conditions(global_preview, on_step=lambda *_: None)

            await user.open("/stale-correction")
            await user.should_see("Шаг 2")
            await user.should_see("Общий лимит превышен")
            await user.should_not_see(ui.button)

    asyncio.run(run())


def test_purchase_error_uses_structured_step_and_normalizes_currency():
    async def run():
        async with user_simulation() as user:
            calls = []

            @ui.page("/purchase-correction")
            def page():
                data = preview("purchase-second")
                data["blockers"][0].update(
                    reason="purchase_total_exceeded",
                    message="Общая сумма покупок превышает 30 000 ₽ ₽.",
                )
                submission_conditions(data, on_step=lambda *args: calls.append(args))

            await user.open("/purchase-correction")
            await user.should_see("Общая сумма покупок превышает 30 000 ₽")
            await user.should_not_see("₽ ₽")
            user.find("Шаг 2").click()
            await asyncio.sleep(0)
            assert calls == [("purchase-second", "amount")]

    asyncio.run(run())
