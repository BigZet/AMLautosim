"""Participant workspace using only the published HTTP contract."""

from __future__ import annotations

import time
import json
import re
from copy import deepcopy
from decimal import Decimal
from datetime import datetime
from uuid import uuid4

from nicegui import ui

from .profile_history import profile_history_panel
from .participant_limits import participant_limits_panel
from .game import GameEditor
from .operation_timeline import timeline_control
from .counterparties import (
    editable_params,
    expanded,
    party_selector,
    party_readonly,
    party_name,
)
from .aml_context import (
    explanation_selector,
    explanation_readonly,
    purpose_options,
    claim_details,
)
from .shap_result import aml_result_view_model, shap_result
from src.aml_workshop_simulator.domain.operation_purposes import default_purpose
from .counterparties import party_options

STATUS = {
    "none": "Игра ещё не создана",
    "draft": "Ожидаем начала игры",
    "active": "Игра идёт",
    "closed": "Приём сценариев завершён",
    "scoring": "Подсчитываем результаты",
    "completed": "Игра завершена",
}


def display_number(value):
    return f"{Decimal(str(value)):,f}".replace(",", " ").replace(".", ",")


def display_operation_amount(value):
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    return display_number(amount.quantize(Decimal("1")) if amount == amount.to_integral_value() else amount)


def display_moment(value):
    return datetime.fromisoformat(value).strftime("%d.%m.%Y, %H:%M")


def credited_outflow(snapshot):
    totals = snapshot["totals"]
    return totals.get("target_outflow", totals["gross_outflow"])


def turnover_summary(snapshot):
    if "target_outflow" in snapshot["totals"]:
        totals = snapshot["totals"]
        ui.label(
            f"Всего потрачено (без комиссий): {display_number(totals['gross_outflow'])} ₽"
        ).classes("text-sm")
        ui.label(
            f"Засчитано в цель: {display_number(totals['target_outflow'])} ₽"
        ).classes("text-sm")
        ui.label(
            f"Покупки: {display_number(totals['purchase_outflow'])} ₽ · Комиссии: {display_number(totals['fees'])} ₽"
        ).classes("text-xs muted")


def scenario_resources(snapshot):
    objective = snapshot["objective"]
    outflow = Decimal(credited_outflow(snapshot))
    target = Decimal(objective["target_outflow"])
    with ui.column().classes("scenario-goal"):
        ui.label("Цель исходящих операций").classes("text-xs muted")
        with ui.row().classes("goal-value-row"):
            with ui.row().classes("goal-amount-row"):
                ui.label(display_number(outflow)).classes("goal-amount")
                ui.label("₽").classes("goal-currency")
            percent = max(0, outflow / target * 100) if target else Decimal(0)
            ui.label(f"{percent:.0f}%").classes("goal-percent")
        ui.linear_progress(
            value=float(max(0, min(outflow / target, 1))) if target else 0,
            show_value=False,
            size="4px",
        ).props("rounded")
        ui.label(f"из {display_number(target)} ₽").classes("goal-target muted")
    with ui.row().classes("scenario-fees"):
        ui.label("Комиссии").classes("muted")
        ui.label(display_number(snapshot["totals"]["fees"]) + " ₽")


def scenario_resource_summary(snapshot, initial):
    values = snapshot["resources_after"]
    with ui.element("div").classes("resource-summary"):
        with ui.column().classes("resource-balance"):
            ui.label("Баланс").classes("resource-caption")
            with ui.row().classes("resource-amount-row"):
                ui.label(display_number(values["balance"])).classes(
                    "resource-amount" + (
                        " resource-negative" if Decimal(str(values["balance"])) < 0 else ""
                    )
                )
                ui.label("₽").classes("resource-currency")
        with ui.column().classes("resource-meters"):
            for key, label in [("energy", "Энергия"), ("time", "Время")]:
                remaining = Decimal(str(values[key]))
                capacity = Decimal(str(initial.get(f"initial_{key}", 0)))
                fraction = float(max(Decimal(0), min(Decimal(1), remaining / capacity))) if capacity > 0 else 0
                with ui.column().classes("resource-meter"):
                    with ui.row().classes("resource-meter-heading"):
                        ui.label(label).classes("resource-caption")
                        ui.label(display_number(values[key])).classes(
                            "resource-meter-value" + (" resource-negative" if remaining < 0 else "")
                        )
                    ui.linear_progress(value=fraction, show_value=False, size="3px").classes(
                        "resource-meter-bar"
                    ).props(f'aria-label="{label}: {display_number(values[key])}"')


def scenario_resource_tiles(snapshot):
    values = snapshot["resources_after"]
    with ui.element("div").classes("resource-grid"):
        for label, key, icon in [
            ("Баланс, ₽", "balance", "account_balance_wallet"),
            ("Энергия", "energy", "bolt"),
            ("Время", "time", "schedule"),
        ]:
            with ui.column().classes("resource-tile"):
                with ui.row().classes("items-center gap-1"):
                    ui.icon(icon).classes("text-sm text-blue-700")
                    ui.label(label).classes("text-xs muted")
                ui.label(display_number(values[key])).classes(
                    "font-semibold text-lg" + (" resource-negative" if Decimal(str(values[key])) < 0 else "")
                )


def submission_conditions(preview, *, current=True, on_step=None):
    snapshot = preview["resources"]

    def condition(label, detail, passed):
        passed = passed and current
        with ui.row().classes(
            "condition-row " + ("condition-ok" if passed else "condition-pending")
        ):
            ui.icon("check_circle" if passed else "radio_button_unchecked").classes(
                "condition-icon"
            )
            ui.label(label).classes("condition-label")
            ui.label(detail).classes("condition-value")

    with ui.column().classes("submission-conditions"):
        ui.label("Лимиты и цель").classes("section-caption")
        objective = snapshot["objective"]
        remaining = max(
            Decimal(objective["target_outflow"]) - Decimal(credited_outflow(snapshot)),
            0,
        )
        condition(
            "Цель",
            "Достигнута"
            if objective["reached"]
            else f"Ещё {display_number(remaining)} ₽",
            objective["reached"],
        )
        for limit in snapshot["limits"]:
            passed = Decimal(limit["used"]) <= Decimal(limit["limit"])
            if limit["code"] == "actions":
                passed = passed and bool(snapshot["per_step"])
            condition(
                limit["label"],
                f"{display_number(limit['used'])} / {display_number(limit['limit'])}"
                + (" ₽" if limit["kind"] == "money" else ""),
                passed,
            )
        if not snapshot["per_step"]:
            ui.label("Добавьте хотя бы одну операцию.").classes("condition-help")
        messages = {
            (v.get("step_id"), v["message"]): v
            for v in preview["blockers"]
            if v["reason"] not in {"scenario_empty", "target_outflow_not_reached"}
        }
        if messages:
            with ui.column().classes("scenario-corrections"):
                ui.label("Ошибки в цепочке").classes("corrections-heading")
                for (_, message), violation in messages.items():
                    # Normalize legacy messages at the presentation boundary.
                    message = re.sub(r"₽(?:\s*₽)+", "₽", message)
                    short = message.split(". ", 1)[0].rstrip(".")
                    short = re.sub(r'Шаг (\d+) «[^»]+»', r'Шаг \1', short)
                    match = re.match(r"^Шаг (\d+)(?:[:,]\s*|\s+)(.*)$", short)
                    step_id = violation.get("step_id")
                    step_index = violation.get("step_index") if step_id else None
                    if match:
                        short = match[2]
                    with ui.row().classes("correction-row"):
                        if step_index is not None:
                            if current and on_step and step_id:
                                ui.button(
                                    f"Шаг {step_index}",
                                    on_click=lambda sid=step_id, field=violation.get("field"): on_step(sid, field),
                                ).props("flat dense no-caps").classes(
                                    "correction-step correction-step-link"
                                ).tooltip(f"Перейти к шагу {step_index}")
                            else:
                                ui.label(f"Шаг {step_index}").classes("correction-step").props(
                                    f'aria-label="Шаг {step_index}"'
                                )
                        short = short[:1].upper() + short[1:]
                        ui.label(short).classes("correction-text").tooltip(message)
        if current and preview["can_submit"]:
            ui.label("Всё готово к отправке").classes("submission-ready")


def scoring_wait_panel(state, cards):
    scenario = state["scenario"]
    snapshot = scenario["resources"]
    scoring = state["round"]["status"] == "scoring"
    with ui.column().classes("scoring-wait"):
        with ui.card().classes("waiting-hero"):
            ui.icon("hourglass_top" if scoring else "task_alt").classes(
                "waiting-symbol"
            )
            ui.label(
                "Подсчитываем результат" if scoring else "Сценарий принят"
            ).classes("waiting-title")
            ui.label(
                "Оценка появится здесь автоматически."
                if scoring
                else "Теперь очередь организатора — ждём запуска оценки."
            ).classes("waiting-caption")
            with ui.row().classes("waiting-stages"):
                for label, icon, active in [
                    ("Отправлен", "check_circle", True),
                    ("Оценка", "hourglass_top", scoring),
                    ("Результат", "bar_chart", False),
                ]:
                    with ui.row().classes(
                        "waiting-stage" + (" is-active" if active else "")
                    ):
                        ui.icon(icon)
                        ui.label(label)
            with ui.row().classes("waiting-note"):
                ui.icon("sync").classes("text-base")
                ui.label("Обновлять страницу не нужно")
        with ui.card().classes("panel submitted-summary"):
            with ui.row().classes("w-full items-center justify-between gap-2"):
                ui.label("Отправленный сценарий").classes("text-lg font-semibold")
                with ui.row().classes("items-center gap-1 text-xs muted"):
                    ui.icon("lock_outline").classes("text-sm")
                    ui.label("Только просмотр")
            with ui.row().classes("submitted-target"):
                ui.icon("check_circle").classes("text-base")
                ui.label(
                    "Цель достигнута"
                    if snapshot["objective"]["reached"]
                    else "Исходящие операции"
                )
                ui.label(
                    f"{display_number(credited_outflow(snapshot))} / {display_number(snapshot['objective']['target_outflow'])} ₽"
                ).classes("submitted-target-value")
            with ui.row().classes("submitted-costs"):
                totals = snapshot["totals"]
                for label, value in [
                    ("Операции без комиссий", totals["gross_outflow"]),
                    ("Из них покупки", totals.get("purchase_outflow", "0")),
                    ("Комиссии", totals["fees"]),
                ]:
                    with ui.row().classes("submitted-cost"):
                        ui.label(label).classes("submitted-cost-label")
                        ui.label(f"{display_number(value)} ₽").classes("submitted-cost-value")
            with ui.element("div").classes("submitted-resources"):
                values = snapshot["resources_after"]
                for key, label in [("balance", "Баланс"), ("energy", "Энергия"), ("time", "Время")]:
                    with ui.column().classes("submitted-resource"):
                        ui.label(label).classes("submitted-resource-label")
                        ui.label(display_number(values[key]) + (" ₽" if key == "balance" else "")).classes("submitted-resource-value")
            with ui.column().classes("submitted-operations"):
                ui.label(f"Операции · {len(scenario['steps'])}").classes("submitted-list-title")
                config = state["round"].get("game_config")
                for index, step in enumerate(scenario["steps"], 1):
                    card = next(
                        (c for c in cards if c["code"] == step["card"]["code"] and c["version"] == step["card"]["version"]),
                        {},
                    )
                    with ui.element("div").classes("submitted-operation"):
                        ui.label(str(index)).classes("submitted-operation-index")
                        with ui.column().classes("submitted-operation-body"):
                            ui.label(card.get("title", step["card"]["code"])).classes("submitted-operation-title")
                            if config and expanded(config):
                                identity = step.get("sender_id") or step.get("recipient_id")
                                name = next((party_name(p) for p in config["behavior"]["counterparties"] if p["id"] == identity), "")
                                details = []
                                if name:
                                    details.append(("От: " if step.get("sender_id") else "Кому: ") + name)
                                if config.get("schema_version") == 10:
                                    purpose = purpose_options(config).get(step.get("purpose_code"))
                                    if purpose:
                                        details.append(purpose)
                                if details:
                                    ui.label(" · ".join(details)).classes("submitted-operation-detail")
                                if config.get("schema_version") == 10 and step.get("claim_id"):
                                    ui.label(claim_details(config, step["claim_id"])).classes("submitted-operation-detail")
                    ui.label(f"{display_operation_amount(step['amount'])} ₽").classes("submitted-operation-amount")


def resources(snapshot):
    turnover_summary(snapshot)
    with ui.row().classes("w-full gap-6"):
        values = snapshot["resources_after"]
        for label, value in [
            ("Баланс", values["balance"]),
            ("Энергия", values["energy"]),
            ("Время", values["time"]),
            ("Осталось шагов", values["available_steps"]),
        ]:
            with ui.column().classes("gap-1"):
                ui.label(label).classes("text-xs muted")
                ui.label(display_number(value)).classes("text-xl font-semibold")
    ui.label(
        f"Исходящие операции: {credited_outflow(snapshot)} / цель {snapshot['objective']['target_outflow']}"
    )
    for limit in snapshot.get("limits", []):
        ui.label(
            f"{limit['label']}: {display_number(limit['used'])} / {display_number(limit['limit'])}"
        ).classes("text-sm muted")


def result_panel(
    result,
    *,
    leaderboard=False,
    selected_tab="summary",
    on_tab_change=None,
    explanation_expanded=False,
    on_explanation_change=None,
    round_config=None,
    scenario_steps=None,
):
    scores = result["scores"]
    steps = result["resources"]["per_step"]
    originals = {s["step_id"]: s for s in scenario_steps or []}
    timing = {
        s["step_id"]: s
        for s in result["resources"].get("timeline", {}).get("steps", [])
    }
    risk_labels = {
        "normal": ("Обычный риск", "Оценка ниже порога проверки."),
        "review": ("Требует проверки", "Оценка достигла порога проверки."),
        "suspicious": (
            "Подозрительный сценарий",
            "Оценка достигла порога подозрительности.",
        ),
    }
    aml_view = (
        aml_result_view_model(result["explanation"])
        if result["explanation"].get("schema_version") in (4, 5)
        else None
    )
    if aml_view:
        risk_title = aml_view["category_title"]
        risk_note = aml_view["context_text"]
        risk_badge = {"low": "normal", "review": "review", "high": "suspicious"}[
            aml_view["category"]
        ]
    else:
        risk_title, risk_note = risk_labels[scores["risk_label"]]
        risk_badge = scores["risk_label"]

    board = None
    with ui.column().classes("result-workspace"):
        with ui.tabs().classes("result-tabs") as tabs:
            ui.tab("summary", label="Итог", icon="emoji_events")
            ui.tab("operations", label="Операции", icon="format_list_numbered")
            if leaderboard:
                ui.tab("ranking", label="Рейтинг", icon="leaderboard")
        if on_tab_change:
            tabs.on_value_change(on_tab_change)
        with ui.tab_panels(tabs, value=selected_tab).classes(
            "w-full bg-transparent result-tab-panels"
        ):
            with ui.tab_panel("summary").classes("p-0"):
                with ui.element("section").classes("result-hero"):
                    with ui.column().classes("gap-2"):
                        ui.label("Ваш результат").classes("text-sm")
                        with ui.row().classes("items-baseline gap-2"):
                            ui.label(display_number(scores["game_score"])).classes(
                                "result-score"
                            )
                            ui.label("из 100 баллов").classes("result-score-caption")
                        ui.label("Итоговая оценка вашего сценария.").classes(
                            "result-score-caption"
                        )
                    with ui.column().classes("result-rank"):
                        ui.icon("emoji_events").classes("text-3xl")
                        ui.label(
                            f"{result['rank']} место"
                            if result.get("rank")
                            else "Без места"
                        ).classes("text-2xl font-semibold")
                        ui.label(
                            "В таблице участников"
                            if result.get("rank")
                            else "Место пока не присвоено"
                        ).classes("text-xs")
                with ui.element("div").classes("result-metrics"):
                    for title, key, note, icon in [
                        (
                            aml_view["title"] if aml_view else "Риск",
                            "risk_score",
                            risk_note if aml_view else "Ниже — лучше. " + risk_note,
                            "policy",
                        ),
                        (
                            "Сбережённые ресурсы",
                            "resource_score",
                            "Выше — экономнее использованы ресурсы.",
                            "savings",
                        ),
                    ]:
                        with ui.card().classes("panel result-metric"):
                            with ui.row().classes("items-center gap-2"):
                                ui.icon(icon).classes("text-blue-700")
                                ui.label(title).classes("font-semibold")
                            ui.label(
                                aml_view["probability_text"]
                                if aml_view and key == "risk_score"
                                else display_number(scores[key]) + " / 100"
                            ).classes("text-2xl font-semibold")
                            ui.label(note).classes("text-xs muted")
                            if key == "risk_score":
                                ui.label(risk_title).classes(
                                    "risk-badge risk-" + risk_badge
                                )

                with ui.card().classes("panel score-calculation w-full min-w-0"):
                    ui.label("Как рассчитан итоговый балл").classes("text-lg font-semibold")
                    weights = (
                        (round_config or {})
                        .get("leaderboard", {})
                        .get("weights", {"stealth": "0.65", "resources": "0.35"})
                    )
                    probability = (
                        Decimal(str(aml_view["explanation"]["aml_probability"]))
                        if aml_view else Decimal(str(scores["risk_score"])) / 100
                    )
                    with ui.element("div").classes("score-breakdown"):
                        for label, value, weight in [
                            ("Низкая подозрительность", 100 * (1 - probability), Decimal(str(weights["stealth"]))),
                            ("Сбережённые ресурсы", Decimal(str(scores["resource_score"])), Decimal(str(weights["resources"]))),
                        ]:
                            with ui.element("div").classes("score-breakdown-row"):
                                ui.label(label).classes("score-breakdown-label")
                                ui.label(f"{display_number(value.quantize(Decimal("0.01")))} × {display_number(weight * 100).rstrip("0").rstrip(",")}%").classes("score-breakdown-value")
                        with ui.element("div").classes("score-breakdown-row score-breakdown-total"):
                            ui.label("Итого")
                            ui.label(f"{display_number(scores['game_score'])} / 100")

                shap_result(
                    result["explanation"],
                    expanded=explanation_expanded,
                    on_change=on_explanation_change,
                )
            with ui.tab_panel("operations").classes("p-0"), ui.card().classes("panel"):
                ui.label(f"Ваши операции · {len(steps)}").classes(
                    "text-lg font-semibold"
                )
                for step in steps:
                    with ui.column().classes("result-operation"):
                        with ui.row().classes("w-full justify-between gap-2"):
                            ui.label(
                                f"{step['step_index']}. {step['card_title']}"
                            ).classes("font-semibold")
                            ui.label(display_number(step["gross"]) + " ₽").classes(
                                "font-semibold"
                            )
                        ui.label(
                            f"Комиссия: {display_number(step['fee'])} ₽ · Энергия: {step['energy_cost']} · Время: {step['time_cost']}"
                        ).classes("text-xs muted")
                        if (
                            round_config
                            and expanded(round_config)
                            and step["step_id"] in originals
                        ):
                            party_readonly(round_config, originals[step["step_id"]])
                            explanation_readonly(
                                round_config, originals[step["step_id"]]
                            )
                        if step["step_id"] in timing:
                            moment = timing[step["step_id"]]
                            ui.label(
                                f"{display_moment(moment['occurred_at'])} · интервал {moment['interval_minutes'] or 0} мин · ожидание: {moment['waiting_time_cost']} ед. ресурса"
                            ).classes("text-xs muted")
                ui.separator()
                resources(result["resources"])
            if leaderboard:
                with ui.tab_panel("ranking").classes("p-0"), ui.card().classes("panel"):
                    ui.label("Результаты участников").classes("text-xl font-semibold")
                    ui.label(
                        "Выше итоговый балл — выше место. Ваша строка отмечена «вы»."
                    ).classes("text-sm muted")
                    board = ui.column().classes("w-full")
    return board


def board_table(data, *, admin=False):
    own = data.get('current_user_row')
    if not admin and own and not any(row.get('is_current_user') for row in data['rows']):
        data = {**data, 'rows': [*data['rows'], own]}
    from src.aml_workshop_simulator.ui.nicegui.shap_result import (
        aml_probability_display,
    )

    kinds = {row.get("score_kind", "legacy_risk") for row in data["rows"]}
    if len(kinds) > 1 or not kinds <= {
        "legacy_risk",
        "aml_probability",
        "educational_pattern_probability",
    }:
        raise ValueError("Leaderboard cannot mix score semantics")
    probability_board = bool(kinds) and kinds <= {
        "aml_probability",
        "educational_pattern_probability",
    }
    pattern_board = kinds == {"educational_pattern_probability"}
    if probability_board:
        ui.label(
            "Соответствие учебным AML-паттернам"
            if pattern_board
            else "Вероятность AML-сценария в учебной модели"
        ).classes("text-sm muted")
    columns = [
        ("rank", "Место"),
        ("display_name", "Участник"),
        ("game_score", "Итоговый балл ↑"),
        (
            "risk_score",
            "Соответствие паттернам ↓"
            if pattern_board
            else "Вероятность AML ↓"
            if probability_board
            else "Риск модели ↓",
        ),
        ("resource_score", "Сбережённые ресурсы ↑"),
        (
            "risk_label",
            "Категория цепочки"
            if pattern_board
            else "Категория вероятности"
            if probability_board
            else "Риск",
        ),
    ]
    if admin:
        columns += [
            ("email", "Email"),
            ("is_blocked", "Заблокирован"),
        ]
    rows = deepcopy(data["rows"])
    for index, row in enumerate(rows):
        row["_row"] = index
        if probability_board:
            view = aml_probability_display(
                row["aml_probability"], row["category"], row["score_kind"]
            )
            row["risk_score"] = view["probability_text"]
            row["risk_label"] = view["category_title"]
        else:
            row["risk_score"] = display_number(
                row.get("risk_score", 100 - Decimal(str(row["stealth_score"])))
            )
        if admin:
            row["is_blocked"] = "Да" if row["is_blocked"] else "Нет"
        for score_key in ("game_score", "stealth_score", "resource_score"):
            row[score_key] = display_number(row[score_key])
        if not probability_board:
            row["risk_label"] = {
                "normal": "Обычный",
                "review": "Проверка",
                "suspicious": "Подозрительно",
            }.get(row["risk_label"], row["risk_label"])
        if row.get("is_current_user"):
            row["display_name"] += " (вы)"
    if not rows:
        ui.label("Пока нет опубликованных результатов.").classes("muted")
    else:
        ui.table(
            columns=[
                {"name": key, "label": label, "field": key, "align": "left"}
                for key, label in columns
            ],
            rows=rows,
            row_key="participant_id" if admin else "_row",
        ).props("flat bordered").classes("w-full")


class ParticipantScreen:
    def __init__(
        self, api, storage, token, guarded, status_label, title_label, section="auto"
    ):
        self.section = section
        self.open_steps = set()
        self.api, self.storage, self.token, self.guarded = api, storage, token, guarded
        self.editor = None
        self.save_status = self.submit_button = self.resource_box = self.error_box = (
            None
        )
        self.resource_overview = None
        self.last_change = 0
        self.ticking = False
        self.submitting = False
        self.render_key = None
        self.board_at = 0
        self.board_version = None
        self.board_content = None
        self.result_tab = "summary"
        self.explanation_expanded = False
        self.resource_render_key = None
        self.status = status_label
        self.title = title_label
        with ui.column().classes("w-full gap-5 participant-workspace"):
            self.body = ui.column().classes("w-full gap-4")
        ui.context.client.on_connect(self.connect)

    async def connect(self):
        if self.editor is not None:
            self.editor.poll_status = None
            self.board_version = None
            await self.poll()
            return
        tab_id = ui.context.client.tab_id
        workspaces = self.storage.get("workspace_play", {})
        record = deepcopy(workspaces.get(tab_id, {}))

        def persist():
            from .auth import credential

            if credential(self.storage, "play") != self.token:
                return
            all_records = dict(self.storage.get("workspace_play", {}))
            all_records[tab_id] = deepcopy(record)
            self.storage["workspace_play"] = all_records

        self.editor = GameEditor(self.api, self.token, record, persist)
        await self.poll()
        ui.timer(0.3, self.tick)

    async def poll(self):
        if self.editor is None:
            return

        async def work():
            version = self.editor.render_revision
            await self.editor.poll()
            self.render(force=version != self.editor.render_revision)
            if (
                self.editor.state.get("can_view_leaderboard")
                and self.section != "profile"
                and ((self.editor.poll_status or {}).get('results_version') != self.board_version
                     or (not self.editor.status_supported and time.monotonic() - self.board_at > 3))
            ):
                self.board_at = time.monotonic()
                board = await self.api.request(
                    "GET",
                    f"rounds/{self.editor.record['key'][0]}/leaderboard",
                    session_id=self.token,
                    params={"limit": 200},
                )
                self.board_version = (self.editor.poll_status or {}).get('results_version')
                content = {'rows': board['rows'], 'current_user_row': board.get('current_user_row')}
                if content != self.board_content:
                    self.board_content = content
                    self.board.clear()
                    with self.board:
                        board_table(board)
                        ui.button('Обновить', on_click=self.refresh_board).props('flat no-caps')

        await self.guarded(work)

    async def refresh_board(self):
        self.board_version = None
        await self.poll()

    def changed(self):
        self.editor.changed()
        self.last_change = time.monotonic()
        self.update_status()

    def render(self, force=False):
        editor = self.editor
        state = editor.state
        round_data = state.get("round")
        status = round_data["status"] if round_data else "none"
        self.title.set_text(round_data["title"] if round_data else "")
        self.title.set_visibility(bool(round_data))
        self.status.set_text(STATUS[status])
        self.status.style(
            "--status-color:" + ("#247c62" if status == "active" else "#77869a")
        )
        self.status.set_visibility(status not in {"none", "draft"})
        key = (
            str(editor.record.get("key")),
            status,
            state.get("can_edit"),
            editor.conflict,
            (state.get("scenario") or {}).get("status")
            if not editor.editable
            else None,
            (state.get("result") or {}).get("rank"),
        )
        if key == self.render_key and not force:
            self.update_status()
            return
        self.render_key = key
        self.body.clear()
        self.board_version = None
        self.board_content = None
        self.body.classes(
            add="chain-workspace" if editor.editable and self.section not in {"profile", "limits"} else "",
            remove="chain-workspace" if not editor.editable or self.section in {"profile", "limits"} else "",
        )
        self.resource_render_key = None
        self.save_status = self.submit_button = self.resource_box = self.error_box = (
            None
        )
        with self.body:
            if status in {"none", "draft"}:
                with ui.column().classes("waiting-room"):
                    ui.icon("hourglass_top").classes("waiting-icon")
                    ui.label("Ожидаем начала игры").classes("text-2xl font-semibold")
                    ui.label(
                        "Экран обновится автоматически, когда организатор начнёт игру."
                    ).classes("muted text-center")
                return
            if not editor.editable and state.get("scenario") and not state.get("result"):
                scoring_wait_panel(state, editor.cards)
                return
            if editor.editable:
                with ui.row().classes("w-full gap-4 participant-nav"):
                    ui.link("Сценарий", "/play").classes("selected" if self.section not in {"profile", "limits"} else "")
                    ui.link("Профиль", "/play/profile").classes("selected" if self.section == "profile" else "")
                    ui.link("Ограничения", "/play/limits").classes("selected" if self.section == "limits" else "")
                    if state.get("can_view_leaderboard"):
                        ui.link("Результаты", "/play/results")
                if self.section == "limits":
                    self.body.classes(add="profile-workspace")
                    participant_limits_panel(round_data, editor.cards)
                    return
                if self.section == "profile":
                    self.body.classes(add="profile-workspace")
                    profile_history_panel(round_data)
                    return
            if state.get("result"):
                self.board = result_panel(
                    state["result"],
                    leaderboard=state.get("can_view_leaderboard", False),
                    selected_tab=self.result_tab,
                    explanation_expanded=self.explanation_expanded,
                    on_explanation_change=lambda e: setattr(
                        self, "explanation_expanded", e.value
                    ),
                    round_config=round_data["game_config"],
                    scenario_steps=(state.get("scenario") or {}).get("steps", []),
                    on_tab_change=lambda e: setattr(self, "result_tab", e.value),
                )
                self.board_at = 0
            if editor.editable:
                if editor.conflict:
                    with ui.card().classes("panel"):
                        ui.label(
                            "Сценарий изменён в другой вкладке. Ваша локальная цепочка сохранена."
                        ).classes("text-orange-800")

                        async def resolve(keep):
                            editor.accept_server(keep_local=keep)
                            self.render(force=True)

                        with ui.row():
                            ui.button(
                                "Загрузить серверную версию",
                                on_click=lambda: resolve(False),
                            ).props("no-caps")
                            ui.button(
                                "Сохранить мою версию поверх актуальной",
                                on_click=lambda: resolve(True),
                            ).props("outline no-caps")
                with ui.element("div").classes("scenario-layout"):
                    with ui.column().classes("scenario-editor"):
                        self.resource_overview = ui.column().classes(
                            "resource-overview"
                        )
                        with ui.column().classes("chain-catalog"):
                            for card in editor.cards:
                                icon = {
                                    "salary": "account_balance_wallet",
                                    "incoming_transfer": "south_west",
                                    "card_transfer": "credit_card",
                                    "cash_withdrawal": "payments",
                                    "purchase": "shopping_bag",
                                }.get(card["code"], "swap_horiz")
                                label = {
                                    "salary": "Зарплата",
                                    "incoming_transfer": "Входящий перевод",
                                    "card_transfer": "Перевод по карте",
                                    "cash_withdrawal": "Наличные",
                                    "purchase": "Покупка",
                                }.get(card["code"], card["title"])
                                (
                                    ui.button(
                                        label,
                                        on_click=lambda c=card: self.add(c),
                                        icon=icon,
                                    )
                                    .props("flat no-caps align=center")
                                    .classes("operation-choice")
                                )
                        self.chain_box = ui.column().classes("w-full gap-3")
                        self.render_chain()
                    with ui.card().classes("panel scenario-summary"):
                        self.resource_box = ui.column().classes("w-full")
                        self.error_box = ui.label().classes("error-box")
                        self.error_box.set_visibility(False)
                        with ui.column().classes("scenario-submit-footer"):
                            ui.label('Отправьте сценарий до закрытия игры: неотправленный черновик будет удалён.').classes('text-sm muted')
                            self.save_status = ui.label().classes("save-indicator")
                            self.retry_button = ui.button(
                                "Повторить запрос", on_click=self.retry
                            ).props("outline no-caps")
                            self.retry_button.set_visibility(False)
                            self.submit_button = (
                                ui.button(
                                    "Отправить сценарий",
                                    on_click=self.confirm_submit,
                                    icon="arrow_forward",
                                )
                                .props("unelevated no-caps")
                                .classes("submit-scenario")
                            )
            elif state.get("scenario") and not state.get("result"):
                scoring_wait_panel(state, editor.cards)
            elif not state.get("result") and status in {
                "closed",
                "scoring",
                "completed",
            }:
                ui.label(
                    "Вы не отправили сценарий до закрытия приёма. Сохранённые черновики удалены."
                ).classes("muted")
            if state.get("can_view_leaderboard") and not state.get("result"):
                with ui.card().classes("panel"):
                    ui.label("Результаты участников").classes("text-xl font-semibold")
                    ui.label(
                        "Выше итоговый балл — выше место. Ваша строка отмечена «вы»."
                    ).classes("text-sm muted")
                    self.board = ui.column().classes("w-full")
                    self.board_at = 0
        self.update_status()

    def add(self, card):
        if self.submitting or not self.editor.editable:
            return
        max_actions = self.editor.state["round"]["game_config"]["objectives"][
            "max_actions"
        ]
        if len(self.editor.steps) >= max_actions:
            ui.notify(
                f"В игре доступно не более {max_actions} операций.", type="warning"
            )
            return
        step = {
            "step_id": str(uuid4()),
            "card": {k: card[k] for k in ("id", "code", "version")},
            "amount": card["min_amount"],
            "context": {},
            "action_details": {},
        }
        config = self.editor.state["round"]["game_config"]
        if expanded(config):
            step.update(sender_id=None, recipient_id=None, interval_minutes=None)
        if config.get("schema_version") == 10:
            step.update(
                purpose_code=default_purpose(step),
                claim_id=None,
            )
        for param in editable_params(card, config):
            target = (
                step["action_details"]
                if param["namespace"] == "action"
                else step["context"]
            )
            target[param["key"]] = param["default"]
        if config.get("schema_version") == 10:
            preferred = {
                "salary": "salary",
                "incoming_transfer": "shared_expense",
                "card_transfer": "shared_expense",
                "purchase": "personal_spending",
                "cash_withdrawal": "personal_spending",
            }.get(card["code"])
            choices = purpose_options(config, step)
            step["purpose_code"] = (
                preferred if preferred in choices else next(iter(choices), None)
            )
        if expanded(config):
            role, options = party_options(config, card["code"], step["action_details"])
            if role:
                step[role] = next(iter(options), None)
            step["interval_minutes"] = 1 if self.editor.steps else None
        self.editor.steps.append(step)
        self.open_steps = {step["step_id"]}
        self.changed()
        self.render_chain()

    def current_step(self, step_id):
        return next(step for step in self.editor.steps if step["step_id"] == step_id)

    async def focus_error_step(self, step_id, field=None):
        # Resolve by identity, never by the displayed position: cards can move.
        if not self.editor.editable or self.submitting:
            return
        operation = self.operation_elements.get(step_id)
        if operation is None or operation.is_deleted:
            return
        self.open_steps.add(step_id)
        operation.open()
        await ui.run_javascript("""
            return new Promise(resolve => setTimeout(() => {
                const card = document.getElementById(%s);
                if (!card) { resolve(); return; }
                const target = %s === 'amount'
                    ? card.querySelector('.operation-amount input') : null;
                card.scrollIntoView({block: 'center', behavior:
                    matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
                const focusTarget = target || card;
                if (focusTarget === card) card.setAttribute('tabindex', '-1');
                focusTarget.focus({preventScroll: true});
                const highlight = target ? target.closest('.operation-amount') : card;
                clearTimeout(highlight.correctionHighlightTimer);
                highlight.removeAttribute('data-correction-highlight');
                void highlight.offsetWidth;
                // Quasar owns the field's class list and updates it after focus.
                highlight.setAttribute('data-correction-highlight', '');
                highlight.correctionHighlightTimer = setTimeout(
                    () => highlight.removeAttribute('data-correction-highlight'), 2200);
                resolve();
            }, 350));
        """ % (json.dumps(f"c{operation.id}"), json.dumps(field)))

    def render_chain(self):
        self.operation_elements = {}
        self.chain_box.clear()
        config = self.editor.state["round"]["game_config"]
        timing = []
        if expanded(config):
            from src.aml_workshop_simulator.domain.operation_timeline import (
                operation_timeline,
            )

            timing = operation_timeline(
                self.editor.steps, config["behavior"]["timeline"]
            )
        with self.chain_box:
            if not self.editor.steps:
                with ui.column().classes("chain-empty"):
                    ui.icon("playlist_add").classes("text-2xl")
                    ui.label("Добавьте первую операцию").classes("font-medium")
            for index in reversed(range(len(self.editor.steps))):
                step = self.editor.steps[index]
                card = next(
                    (
                        c
                        for c in self.editor.cards
                        if all(
                            c[k] == step["card"][k] for k in ("id", "code", "version")
                        )
                    ),
                    None,
                )
                if not card:
                    ui.label("Карточка недоступна. Обновите состояние игры.").classes(
                        "error-box"
                    )
                    continue
                identity = step.get("sender_id") or step.get("recipient_id")
                party = next(
                    (
                        party_name(p)
                        for p in config.get("behavior", {}).get("counterparties", [])
                        if p["id"] == identity
                    ),
                    "Сторона не выбрана"
                    if card["code"] != "cash_withdrawal"
                    else "Наличные",
                )
                moment = display_moment(timing[index]["occurred_at"]) if timing else ""
                amount_text = display_operation_amount(step["amount"]) if step["amount"] else "—"
                summary = f"{index + 1}. {card['title']} · {amount_text} ₽"
                caption = " · ".join(part for part in (party, moment) if part)

                def remember(e, step_id=step["step_id"]):
                    if e.value:
                        self.open_steps.add(step_id)
                    else:
                        self.open_steps.discard(step_id)

                with ui.expansion(
                    summary,
                    caption=caption,
                    value=step["step_id"] in self.open_steps,
                    on_value_change=remember,
                ).classes("operation-card w-full") as operation:
                    self.operation_elements[step["step_id"]] = operation
                    with operation.add_slot("header"):
                        with ui.element("q-item-section").classes("operation-heading"):
                            with ui.row().classes("operation-name"):
                                ui.label(f"{index + 1}. {card['title']}")
                                amount_label = ui.label(f"{amount_text} ₽").classes("operation-heading-amount")
                            caption_label = ui.label(caption).classes("operation-caption")
                        with ui.element("q-item-section").props("side").classes("operation-actions-slot"):
                            actions = ui.row().classes("operation-actions")
                            actions.on("click.stop", lambda: None)
                    with actions:
                        def move(delta, i=index):
                            if self.submitting or not self.editor.editable:
                                return
                            j = i + delta
                            if 0 <= j < len(self.editor.steps):
                                self.editor.steps[i], self.editor.steps[j] = self.editor.steps[j], self.editor.steps[i]
                                self.changed()
                                self.render_chain()

                        # The newest step is displayed first: visually up means later.
                        ui.button(icon="arrow_upward", on_click=lambda m=move: m(1)).props(
                            'flat dense aria-label="Переместить вверх — выполнить позже"'
                        ).tooltip("Вверх — выполнить позже").set_enabled(index < len(self.editor.steps) - 1)
                        ui.button(icon="arrow_downward", on_click=lambda m=move: m(-1)).props(
                            'flat dense aria-label="Переместить вниз — выполнить раньше"'
                        ).tooltip("Вниз — выполнить раньше").set_enabled(index > 0)

                        def remove(i=index):
                            if not self.submitting:
                                self.editor.steps.pop(i)
                                self.changed()
                                self.render_chain()

                        def duplicate(step_id=step["step_id"]):
                            if self.submitting:
                                return
                            limit = self.editor.state["round"]["game_config"][
                                "objectives"
                            ]["max_actions"]
                            if len(self.editor.steps) >= limit:
                                ui.notify(
                                    f"Доступно не более {limit} операций.",
                                    type="warning",
                                )
                                return
                            copied = deepcopy(self.current_step(step_id))
                            copied["step_id"] = str(uuid4())
                            self.editor.steps.append(copied)
                            self.changed()
                            self.render_chain()

                        ui.button(icon="content_copy", on_click=duplicate).props(
                            'flat dense aria-label="Копировать операцию"'
                        ).tooltip("Копировать операцию")
                        ui.button(icon="delete_outline", on_click=remove).props(
                            'flat dense aria-label="Удалить операцию"'
                        ).classes("operation-delete").tooltip("Удалить операцию")
                    with ui.element("div").classes("operation-fields"):

                        def amount(
                            e, step_id=step["step_id"], label=amount_label,
                            expansion=operation, title=f"{index + 1}. {card['title']}",
                        ):
                            if not self.submitting:
                                value = "" if e.value is None else str(e.value).replace(",", ".")
                                self.current_step(step_id)["amount"] = value
                                formatted = display_operation_amount(value) if value else "—"
                                label.set_text(f"{formatted} ₽")
                                expansion.set_text(f"{title} · {formatted} ₽")
                                self.changed()

                        minimum = float(card["min_amount"])
                        maximum = float(card["max_amount"])
                        ui.number(
                            "Сумма",
                            value=float(step["amount"]) if step["amount"] else None,
                            min=minimum,
                            max=maximum,
                            precision=2,
                            step=0.01,
                            suffix="₽",
                            on_change=amount,
                            validation={
                                "Укажите сумму": lambda value: value is not None,
                                f"Минимум {display_number(card['min_amount'])} ₽": lambda value, bound=minimum: (
                                    value is None or value >= bound
                                ),
                                f"Максимум {display_number(card['max_amount'])} ₽": lambda value, bound=maximum: (
                                    value is None or value <= bound
                                ),
                            },
                        ).props(
                            "outlined dense hide-bottom-space inputmode=decimal"
                        ).classes("operation-parameter operation-amount")
                        config = self.editor.state["round"]["game_config"]
                        for param in editable_params(card, config):
                            if config.get("schema_version") in (9, 10) and (
                                (
                                    param["key"] == "bank_country"
                                    and step["action_details"].get("incoming_kind")
                                    != "bank_transfer"
                                )
                                or (
                                    card["code"] == "salary"
                                    and param["key"] == "income_basis"
                                )
                            ):
                                continue
                            if (
                                card["code"] == "incoming_transfer"
                                and param["namespace"] == "channel"
                                and len(param["options"]) == 1
                            ):
                                # The channel default is still stored when adding a step.
                                continue
                            target = (
                                step["action_details"]
                                if param["namespace"] == "action"
                                else step["context"]
                            )

                            def update(
                                e,
                                step_id=step["step_id"],
                                namespace=param["namespace"],
                                k=param["key"],
                            ):
                                if not self.submitting:
                                    current = self.current_step(step_id)
                                    current[
                                        "action_details"
                                        if namespace == "action"
                                        else "context"
                                    ][k] = e.value
                                    if (
                                        config.get("schema_version") in (9, 10)
                                        and k == "incoming_kind"
                                    ):
                                        current["action_details"] = {
                                            "incoming_kind": e.value
                                        }
                                        if e.value == "bank_transfer":
                                            current["action_details"][
                                                "bank_country"
                                            ] = "RU"
                                        _, options = party_options(
                                            config,
                                            current["card"]["code"],
                                            current["action_details"],
                                        )
                                        if current.get("sender_id") not in options:
                                            current["sender_id"] = next(
                                                iter(options), None
                                            )
                                    self.changed()
                                    if (
                                        config.get("schema_version") in (9, 10)
                                        and k == "incoming_kind"
                                    ):
                                        self.render_chain()

                            value = target.get(param["key"], param["default"])
                            if param["kind"] == "toggle":
                                ui.switch(
                                    param["label"], value=bool(value), on_change=update
                                ).classes("operation-toggle").tooltip(
                                    param.get("help") or param["label"]
                                )
                            elif len(param["options"]) == 1:
                                option = param["options"][0]
                                if target.get(param["key"]) != option["value"]:
                                    target[param["key"]] = option["value"]
                                    self.changed()
                                ui.label(
                                    f"{param['label']}: {option['label']}"
                                ).classes("text-sm muted")
                            else:
                                ui.select(
                                    {o["value"]: o["label"] for o in param["options"]},
                                    value=value,
                                    label=param["label"],
                                    on_change=update,
                                ).props("outlined dense options-dense").classes(
                                    "operation-parameter"
                                ).tooltip(param.get("help") or param["label"])

                        if expanded(config):

                            def select_party(
                                role, identity, step_id=step["step_id"],
                                heading=caption_label, operation_moment=moment,
                            ):
                                if not self.submitting and self.editor.editable:
                                    self.current_step(step_id)[role] = identity
                                    if role in ("sender_id", "recipient_id"):
                                        selected = next(
                                            (party_name(p) for p in config["behavior"]["counterparties"] if p["id"] == identity),
                                            "Сторона не выбрана",
                                        )
                                        heading.set_text(" · ".join(v for v in (selected, operation_moment) if v))
                                    self.changed()

                            party_selector(config, step, select_party)
                            explanation_selector(config, step, select_party)

                            def change_interval(value, step_id=step["step_id"]):
                                if not self.submitting and self.editor.editable:
                                    self.current_step(step_id)["interval_minutes"] = (
                                        value
                                    )
                                    self.changed()
                                    self.render_chain()

                            timeline_control(timing[index], config, change_interval)

    def update_status(self):
        if not self.save_status:
            return
        editor = self.editor
        ready = editor.can_submit and not self.submitting
        self.submit_button.set_enabled(ready)
        self.submit_button.props(
            "color=primary text-color=white"
            if ready
            else "color=grey-3 text-color=blue-grey-5"
        )
        self.save_status.set_text(
            "Отправляем…"
            if self.submitting
            else "Сохраняем…"
            if editor.lock.locked()
            else "Есть несохранённые изменения"
            if editor.dirty
            else "Сохранено"
        )
        error = editor.error
        self.error_box.set_visibility(error is not None or not editor.transport_valid())
        if error:
            violations = (error.details or {}).get("violations", [])
            messages = [error.message]
            for violation in violations:
                prefix = (
                    f"Шаг {violation['step_index']}: "
                    if violation.get("step_index") is not None
                    else ""
                )
                message = prefix + violation["message"]
                if message not in messages:
                    messages.append(message)
            self.error_box.set_text("\n".join(messages))
        elif not editor.transport_valid():
            self.error_box.set_text(
                "Введите положительную сумму с точностью до копейки."
            )
        self.retry_button.set_visibility(
            bool(
                error
                and (
                    error.status == 0
                    or error.status in (408, 429)
                    or error.status >= 500
                )
            )
        )
        resource_key = (editor.version, editor.preview_version, id(editor.preview))
        if resource_key == self.resource_render_key:
            return
        self.resource_render_key = resource_key
        if self.resource_overview is not None:
            self.resource_overview.clear()
            if editor.preview:
                with self.resource_overview:
                    initial = (editor.state.get("round") or {}).get("game_config", {}).get("resources", {})
                    scenario_resource_summary(editor.preview["resources"], initial)
        self.resource_box.clear()
        with self.resource_box:
            if editor.preview:
                scenario_resources(editor.preview["resources"])
                if editor.preview_version != editor.version:
                    ui.label(
                        "Пересчитываем…"
                        if not editor.error and editor.transport_valid()
                        else "Расчёт не обновлён"
                    ).classes("text-xs muted")
                with ui.column().classes("w-full open-conditions"):
                    submission_conditions(
                        editor.preview, current=editor.preview_version == editor.version,
                        on_step=self.focus_error_step,
                    )
            else:
                config = (editor.state.get("round") or {}).get("game_config", {})
                if config:
                    start = config["resources"]
                    objective = config["objectives"]
                    ui.label(
                        f"Цель: {display_number(objective['target_outflow'])} ₽ исходящих операций"
                    ).classes("text-lg font-semibold")
                    ui.label(
                        f"На старте: {display_number(start['initial_balance'])} ₽ · Энергия: {start['initial_energy']} · Время: {start['initial_time']} · До {objective['max_actions']} шагов"
                    )
                    ui.label(
                        "Покупки не засчитываются в цель. Остатки появятся после заполнения карточек."
                    ).classes("text-sm muted")

    async def tick(self):
        if self.ticking or not self.editor or self.submitting:
            return
        self.ticking = True

        async def work():
            editor = self.editor
            age = time.monotonic() - self.last_change
            if (
                age >= 0.4
                and editor.editable
                and editor.preview_version != editor.version
                and not editor.error
            ):
                await editor.evaluate()
            if (
                age >= 1
                and editor.dirty
                and editor.editable
                and not editor.error
                and not editor.conflict
            ):
                await editor.write()
            self.update_status()

        try:
            await self.guarded(work, clear_error=False)
        finally:
            self.ticking = False

    async def retry(self):
        async def work():
            self.editor.error = None
            if self.editor.record.get("pending"):
                await self.editor.write()
            await self.editor.poll()
            await self.editor.evaluate()
            self.render(force=True)

        await self.guarded(work)

    async def confirm_submit(self):
        if not self.editor.can_submit:
            return
        with ui.dialog() as dialog, ui.card():
            ui.label("Отправить сценарий окончательно?").classes(
                "text-lg font-semibold"
            )
            ui.label(
                "После отправки изменить цепочку или отправить её повторно нельзя."
            )
            with ui.row():
                ui.button(
                    "Вернуться к редактированию", on_click=lambda: dialog.submit(False)
                ).props("flat no-caps")
                ui.button("Отправить", on_click=lambda: dialog.submit(True)).mark(
                    "confirm-submit"
                ).props("no-caps")
        if not await dialog:
            return
        self.submitting = True
        self.update_status()

        async def work():
            # Resolve any save already in flight before freezing the final command.
            await self.editor.write()
            if self.editor.editable:
                await self.editor.write(submit=True)
            await self.editor.poll()
            self.render(force=True)

        try:
            await self.guarded(work)
        finally:
            self.submitting = False
            self.update_status()
