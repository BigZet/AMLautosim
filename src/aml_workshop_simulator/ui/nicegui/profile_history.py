"""Read-only participant context and structured draft-only organizer fields."""

from datetime import datetime, timedelta
from uuid import uuid4

from nicegui import ui

from .counterparties import INFO, KINDS, category_label, party_name
from src.aml_workshop_simulator.domain.counterparty_roles import party_allowed

from decimal import Decimal


def money(value):
    return f"{Decimal(str(value)):,.2f}".replace(",", " ").replace(".", ",") + " ₽"


OPERATION_LABELS = {
    "salary": "Зарплата",
    "incoming_transfer": "Входящий перевод",
    "card_transfer": "Исходящий перевод",
    "cash_withdrawal": "Снятие наличных",
    "purchase": "Покупка",
}
ROLES = {
    "salary": {"institution"},
    "incoming_transfer": {"person", "institution"},
    "card_transfer": {"person", "institution"},
    "cash_withdrawal": set(),
    "purchase": {"merchant"},
}


def profile_history_panel(round_data):
    summary = round_data.get("context_summary")
    if not summary:
        return
    behavior = round_data["game_config"]["behavior"]
    profile = behavior["profile"]
    parties = {p["id"]: p for p in behavior["counterparties"]}
    coverage = summary.get("coverage")
    with ui.column().classes("profile-section"):
        with ui.column().classes("profile-overview"):
            ui.label(profile['title']).classes("profile-section-title")
            description = profile["description"]
            if description == "Получает зарплату и переводы от знакомых, оплачивает повседневные покупки. Другие доходы неизвестны.":
                description = "Зарплата и переводы от знакомых; повседневные покупки. Другие доходы неизвестны."
            ui.label(description).classes("profile-description")
            if coverage != "unknown":
                period_label = "Часть истории" if coverage == "partial" else "История"
                ui.label(
                    f"{period_label}: {datetime.fromisoformat(summary['starts_at']).strftime('%d.%m.%Y')} — до {datetime.fromisoformat(summary['ends_before']).strftime('%d.%m.%Y')} · до игры, не входит в цель"
                ).classes("profile-period")
        if summary["status"] != "unknown" and coverage != "unknown":
            total = summary["activity"]
            with ui.element("div").classes("profile-metrics profile-totals"):
                for label, value in [("Поступления", money(total['inflow'])), ("Списания", money(total['outflow']))]:
                    with ui.column().classes("profile-metric"):
                        ui.label(label).classes("text-xs muted")
                        ui.label(value).classes("font-semibold")
        with ui.column().classes("profile-subsection"):
            ui.label("Стороны операций").classes("profile-section-title")
            ui.table(
                columns=[
                    {"name": key, "label": label, "field": key, "align": "left"}
                    for key, label in [
                        ("name", "Сторона"),
                        ("kind", "Тип"),
                        ("information", "Сведения"),
                        ("description", "Описание"),
                    ]
                ],
                rows=[
                    {
                        "id": party["id"],
                        "name": party_name(party),
                        "kind": KINDS[party["kind"]],
                        "information": INFO[party["information_status"]],
                        "description": (
                            "Личный знакомый"
                            if party["personal_relationship"] == "known"
                            else "Знакомство неизвестно"
                        ) if party["kind"] == "person" else (
                            category_label(party["category"]) if party.get("category") else "—"
                        ),
                    }
                    for party in parties.values()
                ],
                row_key="id",
                pagination={"rowsPerPage": 0},
            ).props("flat wrap-cells hide-bottom").classes("w-full profile-history-table profile-parties-table")
        if summary["status"] == "unknown" or coverage == "unknown":
            ui.label("История недоступна. Отсутствие операций не установлено.")
            return
        total = summary["activity"]
        if not total["count"]:
            ui.label(
                "В доступном фрагменте истории операций не наблюдалось. Остальная история неизвестна."
                if coverage == "partial"
                else "За наблюдаемый период операций не было."
            )
        with ui.column().classes("profile-subsection"):
            ui.label("История операций").classes("profile-section-title")
            ui.table(
                columns=[
                    {"name": key, "label": label, "field": key, "align": "left"}
                    for key, label in [
                        ("time", "Время"),
                        ("operation", "Операция"),
                        ("amount", "Сумма"),
                        ("party", "Сторона"),
                        ("category", "Категория"),
                    ]
                ],
                rows=[
                    {
                        "id": e["id"],
                        "time": datetime.fromisoformat(e["occurred_at"]).strftime(
                            "%d.%m.%Y, %H:%M"
                        ),
                        "operation": OPERATION_LABELS[e["operation_code"]],
                        "amount": money(e["amount"]),
                        "party": party_name(parties[e["counterparty_id"]])
                        if e["counterparty_id"]
                        else "—",
                        "category": category_label(e["category"])
                        if e["category"]
                        else "—",
                    }
                    for e in summary["events"]
                ],
                row_key="id",
                pagination={"rowsPerPage": 0},
            ).props("flat wrap-cells hide-bottom").classes("w-full profile-history-table")


class ProfileHistoryForm:
    """Mounted only inside the organizer's draft configuration form."""

    def __init__(self, behavior, on_change):
        self.behavior = behavior
        self.on_change = on_change
        with ui.expansion("Профиль и предыстория", value=True).classes("w-full"):
            profile = behavior["profile"]
            for key, label in [
                ("title", "Роль клиента"),
                ("description", "Доступные сведения о клиенте"),
            ]:
                ui.textarea(
                    label,
                    value=profile[key],
                    on_change=lambda e, k=key: self.update(profile, k, e.value),
                ).classes("w-full")
            ui.label(
                "Общие сведения для всех участников. После старта изменить их нельзя."
            )
            self.box = ui.column().classes("w-full")
            self.render()

    def update(self, target, key, value):
        target[key] = value
        self.behavior["history"]["version"] = "observed-history-v1"
        context = self.behavior.get("aml_context")
        if context is not None and target is self.behavior["history"] and key == "operations":
            if value is None:
                context.update(history_coverage="unknown", history_start=None, history_end=None)
            elif context["history_coverage"] == "unknown":
                start = datetime.fromisoformat(self.behavior["timeline"]["starts_at"])
                context.update(history_coverage="complete", history_start=(start - timedelta(days=self.behavior["history"]["window_days"])).isoformat(), history_end=start.isoformat())
        self.on_change()

    def render(self):
        history = self.behavior["history"]
        self.box.clear()
        with self.box:
            ui.label("Период: 30 дней до начала сценария; момент начала не включается.")

            def observed(e):
                self.update(history, "operations", [] if e.value else None)
                self.render()

            ui.switch(
                "История доступна",
                value=history["operations"] is not None,
                on_change=observed,
            )
            if history["operations"] is None:
                ui.label("История неизвестна; это не означает отсутствие активности.")
                return
            for event in history["operations"]:
                with ui.card().classes("w-full"):
                    ui.input(
                        "Дата и время с часовым смещением",
                        value=event["occurred_at"],
                        on_change=lambda e, item=event: self.update(
                            item, "occurred_at", e.value
                        ),
                    ).classes("w-full")

                    def operation(e, item=event):
                        self.update(item, "operation_code", e.value)
                        item["counterparty_id"] = None
                        item["category"] = None
                        for key in ("incoming_kind", "bank_country", "channel", "income_basis"):
                            item.pop(key, None)
                        self.render()

                    ui.select(
                        OPERATION_LABELS,
                        label="Операция в истории",
                        value=event["operation_code"],
                        on_change=operation,
                    )
                    ui.input(
                        "Сумма в истории",
                        value=str(event["amount"]),
                        on_change=lambda e, item=event: self.update(
                            item, "amount", str(e.value).replace(",", ".")
                        ),
                    ).props("inputmode=decimal")
                    kinds = ROLES[event["operation_code"]]
                    if kinds:
                        options = {
                            p["id"]: p["name"]
                            for p in self.behavior["counterparties"]
                            if party_allowed(
                                event["operation_code"],
                                p,
                                self.behavior.get("sender_policy"),
                            )
                        }

                        def select_party(e, item=event):
                            item["category"] = None
                            self.update(item, "counterparty_id", e.value)

                        ui.select(
                            options,
                            label="Сторона в истории",
                            value=event["counterparty_id"],
                            on_change=select_party,
                        )

                    def remove(item=event):
                        history["operations"].remove(item)
                        self.update(history, "operations", history["operations"])
                        self.render()

                    ui.button("Удалить событие", on_click=remove)

            def add():
                start = datetime.fromisoformat(self.behavior["timeline"]["starts_at"])
                history["operations"].append(
                    {
                        "id": str(uuid4()),
                        "occurred_at": (start - timedelta(days=1)).isoformat(),
                        "operation_code": "cash_withdrawal",
                        "amount": "1000.00",
                        "counterparty_id": None,
                        "category": None,
                    }
                )
                self.update(history, "operations", history["operations"])
                self.render()

            ui.button("Добавить событие истории", on_click=add)
