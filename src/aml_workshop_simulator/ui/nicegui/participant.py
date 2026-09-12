"""Participant workspace using only the published HTTP contract."""

from __future__ import annotations

import time
from copy import deepcopy
from decimal import Decimal
from uuid import uuid4

from nicegui import ui

from .game import GameEditor

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


def scenario_resources(snapshot):
    ui.label("Ваш сценарий").classes("text-lg font-semibold")
    objective = snapshot["objective"]
    outflow = Decimal(snapshot["totals"]["gross_outflow"])
    target = Decimal(objective["target_outflow"])
    with ui.column().classes("scenario-goal"):
        ui.label("Цель исходящих операций").classes("text-xs muted")
        ui.label(display_number(outflow)).classes("text-2xl font-semibold")
        ui.linear_progress(
            value=float(max(0, min(outflow / target, 1))) if target else 0,
            show_value=False,
            size="6px",
        ).props("rounded")
        ui.label(f"из {display_number(target)} ₽").classes("text-sm muted")


def scenario_resource_tiles(snapshot):
    values = snapshot["resources_after"]
    with ui.element("div").classes("resource-grid"):
        for label, key, icon in [
            ("Баланс, ₽", "balance", "account_balance_wallet"),
            ("Энергия", "energy", "bolt"),
            ("Время", "time", "schedule"),
            ("Осталось шагов", "available_steps", "format_list_numbered"),
        ]:
            with ui.column().classes("resource-tile"):
                with ui.row().classes("items-center gap-1"):
                    ui.icon(icon).classes("text-sm text-blue-700")
                    ui.label(label).classes("text-xs muted")
                ui.label(display_number(values[key])).classes("font-semibold text-lg")


def submission_conditions(preview, *, current=True):
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
        ui.label("Условия отправки").classes("text-sm font-semibold")
        objective = snapshot["objective"]
        remaining = max(
            Decimal(objective["target_outflow"])
            - Decimal(snapshot["totals"]["gross_outflow"]),
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
        for message in dict.fromkeys(
            v["message"]
            for v in preview["blockers"]
            if v["reason"] not in {"scenario_empty", "target_outflow_not_reached"}
        ):
            ui.label(message).classes("condition-help")
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
                    f"{display_number(snapshot['totals']['gross_outflow'])} / {display_number(snapshot['objective']['target_outflow'])} ₽"
                ).classes("submitted-target-value")
            with ui.column().classes("resource-overview"):
                scenario_resource_tiles(snapshot)
            with ui.expansion(f"Операции · {len(scenario['steps'])}").classes(
                "submitted-operations"
            ):
                for index, step in enumerate(scenario["steps"], 1):
                    card = next(
                        (
                            c
                            for c in cards
                            if c["code"] == step["card"]["code"]
                            and c["version"] == step["card"]["version"]
                        ),
                        {},
                    )
                    with ui.row().classes("submitted-operation"):
                        ui.label(str(index)).classes("submitted-operation-index")
                        ui.label(card.get("title", step["card"]["code"])).classes(
                            "submitted-operation-title"
                        )
                        ui.label(f"{display_number(step['amount'])} ₽").classes(
                            "submitted-operation-amount"
                        )


def resources(snapshot):
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
                ui.label(str(value)).classes("text-xl font-semibold")
    ui.label(
        f"Исходящие операции: {snapshot['totals']['gross_outflow']} / цель {snapshot['objective']['target_outflow']}"
    )
    for limit in snapshot.get("limits", []):
        ui.label(f"{limit['label']}: {limit['used']} / {limit['limit']}").classes(
            "text-sm muted"
        )


def result_panel(
    result, *, leaderboard=False, selected_tab="summary", on_tab_change=None
):
    scores = result["scores"]
    steps = result["resources"]["per_step"]
    risk_labels = {
        "normal": ("Обычный риск", "Оценка ниже порога проверки."),
        "review": ("Требует проверки", "Оценка достигла порога проверки."),
        "suspicious": (
            "Подозрительный сценарий",
            "Оценка достигла порога подозрительности.",
        ),
    }
    risk_title, risk_note = risk_labels[scores["risk_label"]]

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
                        ("Риск", "risk_score", "Ниже — лучше. " + risk_note, "policy"),
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
                            ui.label(display_number(scores[key]) + " / 100").classes(
                                "text-2xl font-semibold"
                            )
                            ui.label(note).classes("text-xs muted")
                            if key == "risk_score":
                                ui.label(risk_title).classes(
                                    "risk-badge risk-" + scores["risk_label"]
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
    columns = [
        ("rank", "Место"),
        ("display_name", "Участник"),
        ("game_score", "Баллы"),
        ("stealth_score", "Скрытность"),
        ("resource_score", "Ресурсы"),
        ("risk_label", "Риск"),
    ]
    if admin:
        columns += [("email", "Email"), ("is_blocked", "Заблокирован")]
    rows = deepcopy(data["rows"])
    for index, row in enumerate(rows):
        row["_row"] = index
        for score_key in ("game_score", "stealth_score", "resource_score"):
            row[score_key] = display_number(row[score_key])
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
    def __init__(self, api, storage, token, guarded, status_label, title_label):
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
        self.result_tab = "summary"
        self.resource_render_key = None
        self.status = status_label
        self.title = title_label
        with ui.column().classes("w-full gap-5 participant-workspace"):
            self.body = ui.column().classes("w-full gap-4")
        ui.context.client.on_connect(self.connect)

    async def connect(self):
        if self.editor is not None:
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
                and time.monotonic() - self.board_at > 3
            ):
                self.board_at = time.monotonic()
                board = await self.api.request(
                    "GET",
                    f"rounds/{self.editor.record['key'][0]}/leaderboard",
                    session_id=self.token,
                    params={"limit": 200},
                )
                self.board.clear()
                with self.board:
                    board_table(board)

        await self.guarded(work)

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
            if state.get("result"):
                self.board = result_panel(
                    state["result"],
                    leaderboard=state.get("can_view_leaderboard", False),
                    selected_tab=self.result_tab,
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
                        ui.label("Добавить операцию").classes("text-lg font-semibold")
                        with ui.row().classes("operation-picker"):
                            for card in editor.cards:
                                icon = {
                                    "salary": "account_balance_wallet",
                                    "incoming_transfer": "south_west",
                                    "card_transfer": "credit_card",
                                    "cash_withdrawal": "payments",
                                }.get(card["code"], "swap_horiz")
                                (
                                    ui.button(
                                        card["title"],
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
                        self.save_status = ui.label().classes("save-indicator")
                        with ui.row().classes("w-full"):
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
        for param in card["visible_params"]:
            target = (
                step["action_details"]
                if param["namespace"] == "action"
                else step["context"]
            )
            target[param["key"]] = param["default"]
        self.editor.steps.append(step)
        self.changed()
        self.render_chain()

    def current_step(self, step_id):
        return next(step for step in self.editor.steps if step["step_id"] == step_id)

    def render_chain(self):
        self.chain_box.clear()
        with self.chain_box:
            if not self.editor.steps:
                ui.label("Добавьте первую операцию из каталога.").classes("muted")
            for index, step in enumerate(self.editor.steps):
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
                with ui.card().classes("operation-card"):
                    with ui.row().classes("operation-header"):
                        ui.label(f"{index + 1}. {card['title']}").classes(
                            "operation-title font-semibold"
                        )
                        ui.space()

                        def move(delta, i=index):
                            if self.submitting:
                                return
                            j = i + delta
                            if 0 <= j < len(self.editor.steps):
                                self.editor.steps[i], self.editor.steps[j] = (
                                    self.editor.steps[j],
                                    self.editor.steps[i],
                                )
                                self.changed()
                                self.render_chain()

                        ui.button(
                            icon="arrow_upward", on_click=lambda m=move: m(-1)
                        ).props('flat dense aria-label="Переместить выше"').tooltip(
                            "Выше"
                        ).set_enabled(index > 0)
                        ui.button(
                            icon="arrow_downward", on_click=lambda m=move: m(1)
                        ).props('flat dense aria-label="Переместить ниже"').tooltip(
                            "Ниже"
                        ).set_enabled(index < len(self.editor.steps) - 1)

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
                            "flat dense"
                        ).tooltip("Копировать операцию")
                        ui.button(icon="delete_outline", on_click=remove).props(
                            "flat dense"
                        ).tooltip("Удалить операцию")
                    with ui.expansion("Об операции").classes("operation-description"):
                        ui.label(card["description"]).classes("text-sm muted")
                    with ui.element("div").classes("operation-fields"):

                        def amount(e, step_id=step["step_id"]):
                            if not self.submitting:
                                self.current_step(step_id)["amount"] = str(
                                    e.value or ""
                                ).replace(",", ".")
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
                        ).classes("operation-parameter")
                        for param in card["visible_params"]:
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
                                    self.changed()

                            value = target.get(param["key"], param["default"])
                            if param["kind"] == "toggle":
                                ui.switch(
                                    param["label"], value=bool(value), on_change=update
                                ).classes("operation-toggle").tooltip(
                                    param.get("help") or param["label"]
                                )
                            else:
                                ui.select(
                                    {o["value"]: o["label"] for o in param["options"]},
                                    value=value,
                                    label=param["label"],
                                    on_change=update,
                                ).props("outlined dense options-dense").classes(
                                    "operation-parameter"
                                ).tooltip(param.get("help") or param["label"])
                    ui.label(f"Лимит операций: {card['max_occurrences']}").classes(
                        "text-xs muted"
                    )

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
        self.retry_button.set_visibility(bool(error))
        resource_key = (editor.version, editor.preview_version, id(editor.preview))
        if resource_key == self.resource_render_key:
            return
        self.resource_render_key = resource_key
        if self.resource_overview is not None:
            self.resource_overview.clear()
            if editor.preview:
                with self.resource_overview:
                    scenario_resource_tiles(editor.preview["resources"])
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
                submission_conditions(
                    editor.preview, current=editor.preview_version == editor.version
                )
            else:
                ui.label("Ресурсы будут рассчитаны после проверки цепочки.").classes(
                    "muted"
                )

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
