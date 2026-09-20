"""Public context and mounted v10 editor behavior across save/reload/submit."""

import asyncio
from copy import deepcopy

import pytest

from tests.aml_context_support import context_fixture
from src.aml_workshop_simulator.services.configuration import snapshot_specs
from src.aml_workshop_simulator.services.projections import card_out
from src.aml_workshop_simulator.ui.nicegui.game import GameEditor


def test_fixed_salary_and_no_empty_claim_selector(tmp_path, monkeypatch):
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation
    from src.aml_workshop_simulator.services.game_classifier import get_game_classifier
    from src.aml_workshop_simulator.ui.nicegui.aml_context import explanation_selector
    from src.aml_workshop_simulator.domain.operation_purposes import default_purpose

    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    config = get_game_classifier().context
    step = {
        "card": {"code": "salary"},
        "action_details": {"income_basis": "payroll_registry"},
    }
    step["purpose_code"] = default_purpose(step)

    async def run():
        async with user_simulation() as user:

            @ui.page("/purpose-salary")
            def page():
                explanation_selector(
                    config, step, lambda key, value: step.update({key: value})
                )

            await user.open("/purpose-salary")
            field = next(e for e in user.find(ui.input).elements if e.value == "Зарплата")
            assert field.props["label"] == "Назначение операции"
            assert field.props["readonly"] is True
            await user.should_not_see("Основание (необязательно)")
            await user.should_not_see(ui.select)

    asyncio.run(run())


def test_v10_editor_keeps_explicit_claim_through_type_change_and_submission(
    tmp_path, monkeypatch
):
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation
    from src.aml_workshop_simulator.ui.nicegui.participant import ParticipantScreen
    from src.aml_workshop_simulator.services.aml_context import canonical_steps

    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    config, _ = context_fixture()
    original_context = deepcopy(config["behavior"]["aml_context"])
    cards = [
        card_out(s, schema_version=10).model_dump(mode="json")
        for s in snapshot_specs(config).values()
    ]
    state = {
        "round": {"id": 1, "config_version": "v10-ui", "game_config": config},
        "can_edit": True,
        "scenario": None,
    }

    class Transport:
        async def request(self, method, path, **kwargs):
            if method == "GET":
                return deepcopy(cards if path.endswith("/cards") else state)
            body = kwargs["body"]
            saved = {
                "steps": canonical_steps(body["steps"], config),
                "revision": body["expected_revision"] + 1,
                "status": "submitted" if path.endswith("/submit") else "editing",
            }
            state["scenario"] = saved
            return deepcopy(saved)

    screen = ParticipantScreen.__new__(ParticipantScreen)
    screen.submitting = False
    screen.open_steps = set()
    screen.editor = GameEditor(Transport(), "test", {}, lambda: None)
    screen.changed = screen.editor.changed

    async def run():
        await screen.editor.poll()
        async with user_simulation() as user:

            @ui.page("/aml-editor")
            def page():
                screen.chain_box = ui.column()
                screen.open_steps = {s["step_id"] for s in screen.editor.steps}
                screen.render_chain()

            await user.open("/aml-editor")
            with user:
                screen.add(next(c for c in cards if c["code"] == "incoming_transfer"))
            step = screen.editor.steps[0]
            assert step.get("purpose_code") == "shared_expense"
            assert step["sender_id"] == "A"
            assert step["action_details"] == {
                "incoming_kind": "bank_transfer",
                "bank_country": "RU",
            }
            assert step.get("claim_id") is None
            assert step["interval_minutes"] is None
            selectors = user.find(ui.select).elements
            purpose = next(s for s in selectors if "shared_expense" in s.options)
            claim = next(s for s in selectors if "shared" in s.options)
            assert claim.value is None
            with user:
                purpose.set_value("shared_expense")
                claim.set_value("shared")
                next(s for s in selectors if "bank_transfer" in s.options).set_value(
                    "exchange_withdrawal"
                )
            # An explicit claim remains selected even when its scope no longer matches.
            assert step["claim_id"] == "shared"
            assert step["purpose_code"] == "unknown"
            assert step["action_details"] == {"incoming_kind": "exchange_withdrawal"}
            assert step["sender_id"] == "exchange"
            # The fixture allows only one purpose for exchange withdrawals.
            canonical_steps([step], config)
            assert not any(
                s.label == "Назначение операции" for s in user.find(ui.select).elements
            )
            assert await screen.editor.write()
            screen.editor = GameEditor(Transport(), "test", {}, lambda: None)
            screen.changed = screen.editor.changed
            await screen.editor.poll()
            await user.open("/aml-editor")
            selectors = user.find(ui.select).elements
            assert screen.editor.steps[0]["purpose_code"] == "unknown"
            # This fixture's catalogue contains only unknown for exchange withdrawals.
            assert not any("shared_expense" in s.options for s in selectors)
            assert next(s for s in selectors if "shared" in s.options).value == "shared"
            assert await screen.editor.write(submit=True)
            assert state["scenario"]["steps"][0]["claim_id"] == "shared"
            assert config["behavior"]["aml_context"] == original_context

    asyncio.run(run())


def test_context_panel_exposes_amounts_periods_and_status_without_editors(
    tmp_path, monkeypatch
):
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation
    from src.aml_workshop_simulator.ui.nicegui import aml_context

    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    config, _ = context_fixture()
    before = deepcopy(config)

    async def run():
        async with user_simulation() as user:

            @ui.page("/aml-context")
            def page():
                aml_context.context_panel(config)

            await user.open("/aml-context")
            for text in (
                "200 000,00",
                "250 000,00",
                "390 000,00",
                "420 000,00",
                "100 000,00",
                "50 000,00",
                "13.09.2026",
                "14.09.2026",
                "UTC+03:00",
                "Подтверждено",
                "Полная",
                "Независимая запись",
            ):
                await user.should_see(text)
            await user.should_not_see(ui.select)
            await user.should_not_see(ui.input)
            assert config == before

    asyncio.run(run())


def test_v10_reordering_canonicalizes_wait_without_replacing_explanation():
    config, steps = context_fixture()
    steps = steps[:2]
    steps[0]["interval_minutes"] = 1440
    steps[1]["interval_minutes"] = None
    editor = GameEditor(None, "test", {"steps": steps}, lambda: None)
    editor.state = {"round": {"game_config": config}}
    editor.changed()
    assert [s["interval_minutes"] for s in editor.steps] == [None, 1]
    assert [s["claim_id"] for s in editor.steps] == ["shared", "shared"]
    assert [s["purpose_code"] for s in editor.steps] == [
        "shared_expense",
        "shared_expense",
    ]


def test_optional_claim_can_be_cleared_and_opening_facts_are_not_transaction_claims(
    tmp_path, monkeypatch
):
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation
    from src.aml_workshop_simulator.ui.nicegui.aml_context import (
        explanation_selector,
        explanation_readonly,
    )

    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    config, steps = context_fixture()
    ctx = config["behavior"]["aml_context"]
    opening = deepcopy(ctx["facts"][0])
    opening.update(id="opening", fact_type="opening_balance", operation_codes=[])
    ctx["facts"].append(opening)
    ctx["opening_balance_facts"] = ["opening"]
    before = deepcopy(ctx)
    step = steps[0]

    async def run():
        async with user_simulation() as user:

            @ui.page("/aml-optional")
            def page():
                explanation_selector(config, step, lambda k, v: step.update({k: v}))

            await user.open("/aml-optional")
            claim = next(
                s for s in user.find(ui.select).elements if "shared" in s.options
            )
            assert "opening" not in claim.options
            with user:
                claim.set_value(None)
            assert step["claim_id"] is None
            assert ctx == before
            with user:
                explanation_readonly(config, step)
            await user.should_see("Основание не выбрано")
            await user.should_see("Назначение операции: Shared expense")

    asyncio.run(run())


def test_evidence_without_counterparties_is_not_presented_as_covering_every_party():
    from src.aml_workshop_simulator.ui.nicegui.aml_context import fact_details

    config, _ = context_fixture()
    fact = config["behavior"]["aml_context"]["facts"][0]
    fact.update(counterparty_ids=[], operation_codes=["cash_withdrawal"])
    text = " · ".join(fact_details(config, fact))
    assert "Без указанной стороны" in text
    assert "Все стороны" not in text


@pytest.mark.parametrize(
    "coverage,label", [("partial", "Частичная"), ("unknown", "Неизвестна")]
)
def test_incomplete_history_is_explicit_and_unknown_has_no_invented_window(
    tmp_path, monkeypatch, coverage, label
):
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation
    from src.aml_workshop_simulator.ui.nicegui.aml_context import context_panel

    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    config, _ = context_fixture()
    ctx = config["behavior"]["aml_context"]
    ctx["history_coverage"] = coverage
    if coverage == "unknown":
        ctx["history_start"] = ctx["history_end"] = None

    async def run():
        async with user_simulation() as user:

            @ui.page("/aml-coverage")
            def page():
                context_panel(config)

            await user.open("/aml-coverage")
            await user.should_see("Полнота истории: " + label)
            if coverage == "unknown":
                await user.should_not_see("Известное окно истории")
            else:
                await user.should_see("14.08.2026")

    asyncio.run(run())


@pytest.mark.parametrize("coverage", ["partial", "unknown"])
def test_profile_history_does_not_infer_absence_from_incomplete_observation(
    tmp_path, monkeypatch, coverage
):
    from nicegui import ui
    from nicegui.storage import Storage
    from nicegui.testing.user_simulation import user_simulation
    from src.aml_workshop_simulator.ui.nicegui.profile_history import (
        profile_history_panel,
    )

    monkeypatch.setattr(Storage, "path", tmp_path / "nicegui")
    config, _ = context_fixture()
    summary = {
        "coverage": coverage,
        "status": "unknown" if coverage == "unknown" else "observed",
        "starts_at": "2026-09-12T09:00:00+03:00",
        "ends_before": "2026-09-13T09:00:00+03:00",
        "timezone": "Europe/Moscow",
        "activity": {"count": 0, "inflow": "0", "outflow": "0"},
        "active_days": 0,
        "events": [],
        "counterparties": [
            {"counterparty_id": "A", "observation": "unknown", "activity": None}
        ],
    }

    async def run():
        async with user_simulation() as user:

            @ui.page("/aml-profile")
            def page():
                profile_history_panel(
                    {"game_config": config, "context_summary": summary}
                )

            await user.open("/aml-profile")
            await user.should_not_see("30 дней:")
            await user.should_not_see("За наблюдаемый период операций не было.")
            if coverage == "partial":
                await user.should_see(
                    "В доступном фрагменте истории операций не наблюдалось"
                )
                await user.should_see("Остальная история неизвестна")
                await user.should_see("12.09.2026")
            else:
                await user.should_see("Отсутствие операций не установлено")
                await user.should_not_see("12.09.2026")

    asyncio.run(run())
