"""Organizer UI: current round, configuration, access, results and audit."""

from __future__ import annotations

from .counterparties import expanded, party_readonly
from .operation_timeline import timeline_summary

from copy import deepcopy

from nicegui import ui

from .client import APIError
from .profile_history import profile_history_panel
from .configuration import ConfigForm, configuration_violation
from .participant import STATUS, board_table, result_panel


class OrganizerScreen:
    def __init__(self, api, storage, token, guarded, title_label=None):
        self.api, self.storage, self.token, self.guarded = api, storage, token, guarded
        self.game_title = title_label
        self.round = None
        self.catalog = None
        self.metadata = None
        self.busy = False
        self.dirty = False
        self.edit_version = 0
        self.render_key = None
        self.edit_revision = None
        self.polling = False
        self.loaded = False
        self.tab_id = None
        self.restored = False
        self.read_versions = {}
        with ui.column().classes("w-full gap-4"):
            self.status = ui.label()
            self.controls = ui.row().classes("gap-2")
            self.config_conflict = ui.label().classes("error-box")
            self.config_conflict.set_visibility(False)
            with ui.tabs().classes("w-full") as self.tabs:
                ui.tab("settings", label="Игра")
                ui.tab("participants", label="Участники")
                ui.tab("results", label="Результаты")
                ui.tab("audit", label="Аудит")
            with ui.tab_panels(self.tabs, value="settings").classes(
                "w-full bg-transparent"
            ):
                with ui.tab_panel("settings").classes("p-0"):
                    self.settings_box = ui.column().classes("w-full")
                with ui.tab_panel("participants").classes("p-0"):
                    with ui.row().classes("w-full items-center"):
                        self.query = (
                            ui.input("Поиск по имени или email")
                            .props("outlined dense")
                            .on("keydown.enter", self.load_participants)
                        )
                        self.access_filter = ui.select(
                            {
                                "all": "Все",
                                "open": "Доступ открыт",
                                "blocked": "Заблокированные",
                            },
                            value="all",
                            on_change=self.load_participants,
                        ).props("outlined dense")
                        self.scenario_filter = ui.select(
                            {
                                "all": "Все сценарии",
                                "none": "Не отправлен",
                                "submitted": "Отправлен",
                                "scored": "Оценён",
                            },
                            value="all",
                            on_change=self.load_participants,
                        ).props("outlined dense")
                        ui.button("Обновить", on_click=self.load_participants).props(
                            "outline no-caps"
                        )
                    self.participants_box = ui.column().classes("w-full")
                with ui.tab_panel("results").classes("p-0"):
                    self.results_box = ui.column().classes("w-full")
                with ui.tab_panel("audit").classes("p-0"):
                    with ui.row():
                        self.event_filter = ui.input(
                            "Тип события (необязательно)"
                        ).props("outlined dense")
                        ui.button("Обновить", on_click=self.load_audit).props(
                            "outline no-caps"
                        )
                    self.audit_box = ui.column().classes("w-full")
        self.tabs.on_value_change(self.tab_changed)
        ui.context.client.on_connect(self.connect)

    async def connect(self):
        self.tab_id = ui.context.client.tab_id
        await self.poll()

    def persist(self):
        from .auth import credential

        if self.tab_id is None or credential(self.storage, "admin") != self.token:
            return
        records = dict(self.storage.get("workspace_admin", {}))
        if self.dirty and self.round and self.round["status"] == "draft":
            records[self.tab_id] = {
                "round_id": self.round["id"],
                "revision": self.edit_revision,
                "title": self.title_input.value,
                "config": deepcopy(self.config_form.config),
            }
        else:
            records.pop(self.tab_id, None)
        self.storage["workspace_admin"] = records

    async def request(self, method, path, body=None, params=None, timeout=15):
        return await self.api.request(
            method,
            path,
            session_id=self.token,
            body=body,
            params=params,
            timeout=timeout,
        )

    def begin_read(self, panel):
        """Only the latest request for this panel and game may update its contents."""
        round_id = self.round["id"]
        version = self.read_versions.get(panel, 0) + 1
        self.read_versions[panel] = version

        def current():
            from .auth import credential

            return (
                self.round is not None
                and self.round["id"] == round_id
                and self.read_versions.get(panel) == version
                and credential(self.storage, "admin") == self.token
            )

        return round_id, current

    async def tab_changed(self):
        if self.tabs.value == "participants":
            await self.load_participants()
        elif self.tabs.value == "results":
            await self.load_results()
        elif self.tabs.value == "audit":
            await self.load_audit()

    async def poll(self):
        if self.polling:
            return
        self.polling = True

        async def work():
            current = await self.request("GET", "admin/rounds/current")
            old_id = self.round["id"] if self.round else None
            new_id = current["id"] if current else None
            if old_id != new_id:
                self.participants_box.clear()
                self.results_box.clear()
                self.audit_box.clear()
                self.dirty = False
                self.edit_revision = None
                self.render_key = None
                self.config_conflict.set_visibility(False)
            self.round = current
            if not current or current["status"] != "draft":
                self.dirty = False
                self.restored = True
                self.config_conflict.set_visibility(False)
                self.persist()
            if self.metadata is None:
                self.metadata = await self.request(
                    "GET", "admin/game-config/editor-metadata"
                )
                self.catalog = await self.request("GET", "admin/action-cards")
            await self.render()
            self.loaded = True

        try:
            await self.guarded(work)
        finally:
            self.polling = False

    async def render(self):
        current = self.round
        if getattr(self, "game_title", None) is not None:
            self.game_title.set_text(current["title"] if current else "")
            self.game_title.set_visibility(bool(current))
        status = current["status"] if current else "none"
        self.status.set_text(STATUS[status])
        if current and current.get("scoring_error"):
            self.status.set_text(
                "Ошибка расчёта. Приём закрыт; скоринг можно повторить."
            )
        key = (
            (current["id"], current["status"], current["config_revision"])
            if current
            else None
        )
        if self.loaded and key == self.render_key:
            return
        self.render_key = key
        self.controls.clear()
        with self.controls:
            if status == "draft":
                ui.button("Начать игру", on_click=lambda: self.command("start")).props(
                    "no-caps"
                ).bind_enabled_from(self, "can_start")
            if status in {"active", "closed", "scoring"}:
                ui.button(
                    "Запустить скоринг" if status == "active" else "Повторить скоринг",
                    on_click=lambda: self.command("score"),
                ).props("no-caps")
            if current:
                ui.button("Новая игра", on_click=lambda: self.command("restart")).props(
                    "outline no-caps"
                )
        if self.dirty and status == "draft" and hasattr(self, "config_form"):
            if current["config_revision"] != self.edit_revision:
                self.config_conflict.set_text(
                    "Настройки изменены в другом окне. Скопируйте нужные значения и загрузите актуальную конфигурацию."
                )
                self.config_conflict.set_visibility(True)
            return
        self.settings_box.clear()
        with self.settings_box, ui.card().classes("panel"):
            if not current:
                self.title_input = (
                    ui.input("Название игры", value="Мастер-класс AML")
                    .props("outlined")
                    .classes("w-full")
                )
                self.new_game_mode = ui.select(
                    {
                        v: ("Базовая игра" if v == 7 else "Расширенная игра")
                        for v in [8]
                    },
                    value=8,
                    label="Правила новой игры",
                )
                ui.button("Создать игру", on_click=self.create).props("no-caps")
                return
            if status != "draft":
                ui.label(
                    "Модель: " + current["game_config"]["risk_model"]["model_version"]
                )
                profile_history_panel(current)
                ui.label("Настройки зафиксированы до следующей игры.").classes("muted")
                with ui.expansion("Настройки текущей игры").classes("w-full"):
                    ui.json_editor(
                        {"content": {"json": current["game_config"]}, "readOnly": True}
                    ).classes("w-full")
                if current.get("scoring_summary"):
                    summary = current["scoring_summary"]
                    ui.label(
                        f"Отправлено: {summary['submitted_count']}. Оценено: {summary['scored_count']}."
                    )
                return
            record = {}
            if not self.restored:
                record = self.storage.get("workspace_admin", {}).get(self.tab_id, {})
                self.restored = True
            if record.get("round_id") != current["id"]:
                record = {}
            self.edit_revision = record.get("revision", current["config_revision"])
            self.title_input = (
                ui.input(
                    "Название игры",
                    value=record.get("title", current["title"]),
                    on_change=self.changed,
                )
                .props("outlined")
                .classes("w-full")
            )
            self.config_form = ConfigForm(
                record.get("config", current["game_config"]),
                self.catalog,
                self.metadata,
                self.changed,
            )
            if record:
                self.dirty = True
                if self.edit_revision != current["config_revision"]:
                    self.config_conflict.set_text(
                        "Настройки изменены в другом окне. Скопируйте нужные значения и загрузите актуальную конфигурацию."
                    )
                    self.config_conflict.set_visibility(True)
            self.persist()
            with ui.row():
                ui.button("Сохранить настройки", on_click=self.save).props(
                    "no-caps"
                ).bind_enabled_from(self, "command_ready")
                ui.button("Загрузить актуальные", on_click=self.reload_config).props(
                    "flat no-caps"
                )
                ui.button("Базовые настройки", on_click=self.defaults).props(
                    "outline no-caps"
                )

    def changed(self):
        self.dirty = True
        self.edit_version += 1
        self.persist()

    async def reload_config(self):
        if self.dirty and not await self.confirm(
            "Отменить несохранённые изменения настроек?"
        ):
            return
        self.dirty = False
        self.persist()
        self.loaded = False
        self.config_conflict.set_visibility(False)
        await self.poll()

    async def defaults(self):
        if not await self.confirm(
            "Заменить форму базовыми настройками? Изменения применятся после сохранения."
        ):
            return

        async def work():
            config = await self.request(
                "GET",
                f"admin/game-config/default?schema_version={self.round['game_config']['schema_version']}",
            )
            self.settings_box.clear()
            with self.settings_box, ui.card().classes("panel"):
                self.title_input = (
                    ui.input(
                        "Название игры",
                        value=self.round["title"],
                        on_change=self.changed,
                    )
                    .props("outlined")
                    .classes("w-full")
                )
                self.config_form = ConfigForm(
                    config, self.catalog, self.metadata, self.changed
                )
                ui.button("Сохранить настройки", on_click=self.save).props(
                    "no-caps"
                ).bind_enabled_from(self, "command_ready")
                ui.button("Загрузить актуальные", on_click=self.reload_config).props(
                    "flat no-caps"
                )
            self.changed()

        await self.guarded(work)

    async def create(self):
        if self.busy:
            return
        self.busy = True

        async def work():
            payload = {"title": self.title_input.value}
            if self.new_game_mode.value == 8:
                payload["game_config"] = await self.request(
                    "GET", "admin/game-config/default?schema_version=8"
                )
            await self.request("POST", "admin/rounds", payload)
            self.loaded = False
            await self.poll()

        try:
            await self.guarded(work)
        finally:
            self.busy = False

    @property
    def command_ready(self):
        return not self.busy

    @property
    def can_start(self):
        return not self.busy and not self.dirty

    async def save(self):
        if self.busy:
            return
        self.busy = True
        round_id = self.round["id"]
        version = self.edit_version
        payload = {
            "title": self.title_input.value,
            "game_config": deepcopy(self.config_form.config),
            "expected_config_revision": self.edit_revision,
        }

        async def work():
            try:
                saved = await self.request("PUT", f"admin/rounds/{round_id}", payload)
            except APIError as exc:
                violations = (exc.details or {}).get("violations", [])
                if violations:
                    exc.message += "\n" + "\n".join(
                        configuration_violation(v) for v in violations
                    )
                raise
            if not self.round or self.round["id"] != round_id:
                return
            self.edit_revision = saved["config_revision"]
            self.dirty = self.edit_version != version
            self.persist()
            self.loaded = False
            self.config_conflict.set_visibility(False)
            await self.poll()
            # Saving rebuilds the form and deletes the callback's original slot.
            with self.settings_box:
                ui.notify("Настройки сохранены", type="positive")

        try:
            await self.guarded(work)
        finally:
            self.busy = False

    async def confirm(self, message, *, reason=False, versions=False):
        if versions:
            self.metadata = await self.request(
                "GET", "admin/game-config/editor-metadata"
            )
        with ui.dialog() as dialog, ui.card().classes("max-w-lg"):
            ui.label(message).classes("text-lg")
            mode = (
                ui.select(
                    {
                        v: (
                            "Базовая игра"
                            if v == 7
                            else "Расширенная игра: стороны, время, покупки и история"
                        )
                        for v in [8]
                    },
                    value=8,
                    label="Правила новой игры",
                )
                if versions
                else None
            )
            field = (
                ui.textarea("Причина (10–500 символов)")
                .props("outlined maxlength=500")
                .classes("w-full")
                if reason
                else None
            )
            with ui.row():
                ui.button("Отмена", on_click=lambda: dialog.submit(None)).props(
                    "flat no-caps"
                )
                button = ui.button(
                    "Подтвердить",
                    on_click=lambda: dialog.submit(
                        mode.value if mode else field.value if field else True
                    ),
                ).props("no-caps")
                if field:
                    button.bind_enabled_from(
                        field, "value", backward=lambda v: len((v or "").strip()) >= 10
                    )
        result = await dialog
        dialog.delete()
        return result

    async def command(self, command):
        if self.busy or not self.round or (command == "start" and self.dirty):
            return
        round_id = self.round["id"]
        messages = {
            "start": "Начать игру? После начала настройки нельзя изменить.",
            "score": "Закрыть приём и рассчитать результаты? Все неотправленные черновики будут удалены.",
            "restart": "Создать новую игру? Сценарии, результаты и аудит текущей игры будут удалены. Аккаунты и входы сохранятся.",
        }
        self.busy = True
        try:
            choice = await self.confirm(
                messages[command], versions=command == "restart"
            )
            if not choice:
                return

            async def work():
                try:
                    await self.request(
                        "POST",
                        f"admin/rounds/{round_id}/{command}"
                        + (f"?schema_version={choice}" if command == "restart" else ""),
                        timeout=120 if command == "score" else 15,
                    )
                finally:
                    self.loaded = False
                    await self.poll()

            await self.guarded(work)
        finally:
            self.busy = False

    async def load_participants(self):
        if not self.round:
            return
        round_id, current = self.begin_read("participants")
        query = self.query.value or ""

        async def work():
            data = await self.request(
                "GET",
                f"admin/rounds/{round_id}/participants",
                params={"query": query, "limit": 500},
            )
            if not current():
                return
            self.participants_box.clear()
            with self.participants_box:
                if len(data["rows"]) == 500:
                    ui.label("Показаны первые 500 записей. Уточните поиск.").classes(
                        "muted"
                    )
                count = 0
                for person in data["rows"]:
                    if self.access_filter.value != "all" and person["is_blocked"] != (
                        self.access_filter.value == "blocked"
                    ):
                        continue
                    if (
                        self.scenario_filter.value != "all"
                        and person["scenario_status"] != self.scenario_filter.value
                    ):
                        continue
                    count += 1
                    with (
                        ui.card().classes("panel"),
                        ui.row().classes("w-full items-center"),
                    ):
                        with ui.column().classes("gap-1"):
                            ui.label(person["display_name"]).classes("font-semibold")
                            ui.label(person["email"]).classes("text-sm muted")
                            ui.label(
                                {
                                    "none": "Не отправлен",
                                    "submitted": "Отправлен",
                                    "scored": "Оценён",
                                }[person["scenario_status"]]
                            ).classes("text-sm")
                        ui.space()
                        ui.button(
                            "Подробнее",
                            on_click=lambda p=person: self.detail(round_id, p["id"]),
                        ).props("flat no-caps")
                        ui.button(
                            "Разблокировать"
                            if person["is_blocked"]
                            else "Заблокировать",
                            on_click=lambda p=person: self.access(round_id, p),
                        ).props("outline no-caps")
                if not count:
                    ui.label("Участники не найдены.").classes("muted")

        await self.guarded(work)

    async def access(self, round_id, person):
        reason = await self.confirm(
            ("Разблокировать " if person["is_blocked"] else "Заблокировать ")
            + person["display_name"]
            + "?",
            reason=True,
        )
        if not reason:
            return

        async def work():
            await self.request(
                "PUT",
                f"admin/rounds/{round_id}/participants/{person['id']}/access",
                {
                    "blocked": not person["is_blocked"],
                    "reason": reason,
                    "expected_access_revision": person["access_revision"],
                },
            )
            await self.load_participants()

        await self.guarded(work)

    async def detail(self, round_id, person_id):
        if not self.round or self.round["id"] != round_id:
            return
        _, current = self.begin_read("detail")

        async def work():
            data = await self.request(
                "GET", f"admin/rounds/{round_id}/participants/{person_id}"
            )
            if not current():
                return
            with ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl"):
                ui.label(data["user"]["display_name"]).classes("text-xl")
                ui.label(data["user"]["email"])
                if data["user"].get("blocked_reason"):
                    ui.label("Причина блокировки: " + data["user"]["blocked_reason"])
                if data["result"]:
                    result_panel(data["result"])
                if data["scenario"]:
                    from .participant import turnover_summary

                    turnover_summary(data["scenario"]["resources"])
                    timeline_summary(data["scenario"]["resources"])
                    snapshots = (
                        self.round["game_config"]["card_snapshots"]
                        if self.round and self.round["id"] == round_id
                        else []
                    )
                    for index, step in enumerate(data["scenario"]["steps"], 1):
                        card = next(
                            (
                                c
                                for c in snapshots
                                if c["code"] == step["card"]["code"]
                                and c["version"] == step["card"]["version"]
                            ),
                            {},
                        )
                        ui.label(
                            f"{index}. {card.get('title', step['card']['code'])} — {step['amount']}"
                        ).classes("font-semibold")
                        if self.round and expanded(self.round["game_config"]):
                            party_readonly(self.round["game_config"], step)
                        for section, declarations in [
                            ("context", card.get("context_fields", [])),
                            ("action_details", card.get("fields", [])),
                        ]:
                            declared = {field["key"]: field for field in declarations}
                            for key, value in step[section].items():
                                field = declared.get(key, {})
                                label = field.get(
                                    "label",
                                    self.metadata["labels"].get(
                                        key, "Канал" if key == "channel" else key
                                    ),
                                )
                                options = {
                                    o["value"]: o["label"]
                                    for o in field.get("options", [])
                                }
                                text = (
                                    ("Да" if value else "Нет")
                                    if isinstance(value, bool)
                                    else options.get(
                                        value,
                                        self.metadata["labels"].get(
                                            str(value), str(value)
                                        ),
                                    )
                                )
                                ui.label(f"{label}: {text}").classes("text-sm muted")
                else:
                    ui.label("Нет отправленного сценария.")
                ui.button("Закрыть", on_click=dialog.close).props("no-caps")
            dialog.open()

        await self.guarded(work)

    async def load_results(self):
        if not self.round:
            return
        round_id, current = self.begin_read("results")

        async def work():
            data = await self.request("GET", f"admin/rounds/{round_id}/leaderboard")
            if not current():
                return
            self.results_box.clear()
            with self.results_box, ui.card().classes("panel"):
                board_table(data, admin=True)
                ui.button("Обновить", on_click=self.load_results).props("flat no-caps")

        await self.guarded(work)

    async def load_audit(self):
        if not self.round:
            return
        round_id, current = self.begin_read("audit")
        event_type = self.event_filter.value or ""

        async def work():
            data = await self.request(
                "GET",
                f"admin/rounds/{round_id}/audit-events",
                params={"limit": 200, "event_type": event_type},
            )
            if not current():
                return
            self.audit_box.clear()
            with self.audit_box, ui.card().classes("panel"):
                ui.label("Последние события (до 200 записей)").classes("muted")
                ui.table(
                    columns=[
                        {"name": k, "field": k, "label": label, "align": "left"}
                        for k, label in [
                            ("created_at", "Время"),
                            ("event_type", "Событие"),
                            ("actor_user_id", "Автор"),
                            ("reason", "Причина"),
                            ("request_id", "Код запроса"),
                        ]
                    ],
                    rows=data["rows"],
                    row_key="id",
                ).classes("w-full")

        await self.guarded(work)
