"""Read-only participant context and structured draft-only organizer fields."""

from datetime import datetime, timedelta
from uuid import uuid4

from nicegui import ui

from .counterparties import category_label, party_name
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
    with ui.expansion("Профиль и предыстория", value=True).classes("w-full"):
        ui.label(f"Роль клиента: {profile['title']}").classes("font-semibold")
        ui.label(profile["description"])
        if coverage != "unknown":
            period_label = (
                "Доступный фрагмент истории"
                if coverage == "partial"
                else "Период истории"
                if coverage
                else "30 дней"
            )
            ui.label(
                f"{period_label}: {datetime.fromisoformat(summary['starts_at']).strftime('%d.%m.%Y, %H:%M')} — до {datetime.fromisoformat(summary['ends_before']).strftime('%d.%m.%Y, %H:%M')} · {summary['timezone']}"
            )
        ui.label("История не меняет начальные ресурсы и не засчитывается в цель.")
        if summary["status"] == "unknown" or coverage == "unknown":
            ui.label("История недоступна. Отсутствие операций не установлено.")
            return
        total = summary["activity"]
        ui.label(
            f"Операций в истории: {total['count']} · Дней с активностью: {summary['active_days']}"
        )
        ui.label(
            f"Поступления: {money(total['inflow'])} · Списания: {money(total['outflow'])}"
        )
        if not total["count"]:
            ui.label(
                "В доступном фрагменте истории операций не наблюдалось. Остальная история неизвестна."
                if coverage == "partial"
                else "За наблюдаемый период операций не было."
            )
        with ui.expansion("Связи со сторонами").classes("w-full"):
            ui.label(
                "Личное знакомство и операции в доступной истории — разные сведения."
                if coverage
                else "Личное знакомство и операции за последние 30 дней — разные сведения."
            )
            for item in summary["counterparties"]:
                if item["observation"] == "unknown":
                    relation = "сведения об операциях неполны; отсутствие операций не установлено"
                elif item["observation"] == "absent":
                    relation = "операций не наблюдалось"
                else:
                    relation = f"операций: {item['activity']['count']}"
                ui.label(f"{parties[item['counterparty_id']]['name']} — {relation}")
        with ui.expansion("События предыстории").classes("w-full"):
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
                pagination=10,
            ).classes("w-full")


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
