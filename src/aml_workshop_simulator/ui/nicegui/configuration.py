"""Structured configuration form. No backend imports or local game files."""

from copy import deepcopy

from nicegui import ui

from .profile_history import ProfileHistoryForm
from .counterparties import catalog_form


def configuration_violation(violation):
    parts = (violation.get("field") or "").split(".")
    labels = {
        "name": "название",
        "kind": "тип",
        "category": "категория",
        "information_status": "доступные сведения",
        "personal_relationship": "знакомство",
        "occurred_at": "дата",
        "amount": "сумма",
        "counterparty_id": "сторона",
        "starts_at": "начало сценария",
        "timezone": "часовой пояс",
    }
    prefix = ""
    for section, title in (("counterparties", "Сторона"), ("operations", "Операция")):
        if section in parts:
            index = parts.index(section) + 1
            if index < len(parts) and parts[index].isdigit():
                prefix = f"{title} {int(parts[index]) + 1}"
                break
    label = labels.get(parts[-1], "")
    subject = ", ".join(p for p in (prefix, label) if p)
    return (subject + ": " if subject else "") + violation["message"]


class ConfigForm:
    def __init__(self, config, catalog, metadata, on_change):
        self.config = deepcopy(config)
        self.model_identity = self.config.pop("risk_model", None)
        self.config.pop("config_version", None)
        snapshots = self.config.pop("card_snapshots", [])
        self.catalog = {(c["code"], c["version"]): c for c in catalog}
        # Keep the saved card vocabulary when the live catalog has moved on.
        for card in snapshots:
            self.catalog[(card["code"], card["version"])] = card
        self.metadata = metadata
        self.labels = metadata["labels"]
        self.on_change = on_change
        self.render()

    def text_number(self, target, key, label=None, integer=False):
        def update(e):
            raw = str(e.value or "").replace(",", ".")
            # Keep incomplete input visible; the API returns a field error on save.
            target[key] = int(raw) if integer and raw.lstrip("-").isdigit() else raw
            self.on_change()

        return (
            ui.input(
                label or self.labels.get(key, key),
                value=str(target[key]),
                on_change=update,
            )
            .props(
                "outlined dense inputmode=decimal"
                + (" readonly" if self.config.get("schema_version") == 8 else "")
            )
            .classes("min-w-48 flex-1")
        )

    def numeric_tree(self, values):
        for key, value in values.items():
            if isinstance(value, dict):
                with ui.expansion(self.labels.get(key, key)).classes("w-full"):
                    self.numeric_tree(value)
            else:
                self.text_number(values, key, integer=isinstance(value, int))

    def render(self):
        if self.config.get("schema_version") == 10:
            ui.label(
                "История, цель и ограничения закреплены за проверенным классификатором и одинаковы для всех участников."
            ).classes("text-sm muted")
            with ui.row().classes("w-full gap-4"):
                for section in ("resources", "objectives"):
                    for key, value in self.config[section].items():
                        ui.input(self.labels.get(key, key), value=str(value)).props(
                            "outlined dense readonly"
                        )
            with ui.expansion("Общая неизменная предыстория").classes("w-full"):
                for event in self.config["behavior"]["history"]["operations"]:
                    ui.label(
                        f"{event['occurred_at']} · {event['operation_code']} · {event['amount']}"
                    )
            return
        is_expanded = self.config.get("schema_version") == 8
        if is_expanded:
            ui.label(
                "Финансовые правила закреплены за моделью: ресурсы, цель, лимиты и стоимость операций доступны только для просмотра."
            ).classes("text-sm muted")
            catalog_form(self.config["behavior"], self.on_change)
            with ui.expansion("Начало сценария и время").classes("w-full"):
                timeline = self.config["behavior"]["timeline"]
                for key, label in [
                    ("starts_at", "Начало сценария с часовым смещением"),
                    ("timezone", "Часовой пояс"),
                ]:
                    ui.input(
                        label,
                        value=timeline[key],
                        on_change=lambda e, k=key: (
                            timeline.__setitem__(k, e.value),
                            self.on_change(),
                        ),
                    )
                ui.label(
                    "Ожидание 1 / 10 / 60 / 1440 минут стоит 0 / 1 / 2 / 4 времени; базовая стоимость операции учитывается отдельно."
                )
            ProfileHistoryForm(self.config["behavior"], self.on_change)
        for key, title in [
            ("resources", "Начальные ресурсы"),
            ("objectives", "Цель и число шагов"),
        ]:
            with (
                ui.expansion(title, value=True).classes("w-full"),
                ui.row().classes("w-full"),
            ):
                for field, value in self.config[key].items():
                    self.text_number(
                        self.config[key], field, integer=isinstance(value, int)
                    )
        with ui.expansion("Ограничения").classes("w-full"):
            for key, value in self.config["constraints"].items():
                if key != "category_limits":
                    self.text_number(self.config["constraints"], key, integer=True)
            for code, label in self.metadata["quotas"].items():
                limits = self.config["constraints"]["category_limits"]
                with ui.row().classes("w-full items-center"):

                    def set_enabled(e, c=code, limits=limits):
                        if e.value:
                            limits[c] = "0.00"
                        else:
                            limits.pop(c, None)
                        self.on_change()

                    toggle = ui.switch(
                        label, value=code in limits, on_change=set_enabled
                    )
                    field = ui.input(
                        "Лимит",
                        value=str(limits.get(code, "0.00")),
                        on_change=lambda e, c=code, limits=limits: (
                            limits.__setitem__(c, str(e.value).replace(",", ".")),
                            self.on_change(),
                        ),
                    )
                    field.props("outlined dense").bind_enabled_from(toggle, "value")
                    if is_expanded:
                        toggle.disable()
                        field.props("readonly")
        with ui.expansion("Карточки и параметры", value=True).classes("w-full"):
            self.operations_box = ui.column().classes("w-full")
            self.operations()
        if is_expanded:
            if self.model_identity:
                ui.label("Модель: " + self.model_identity["model_version"])
            ui.label(
                "Риск рассчитывает CatBoost. После завершения раунда участники увидят объяснение SHAP."
            )
            return
        with ui.expansion("Расчёт ресурсов").classes("w-full"):
            self.numeric_tree(self.config["resource_rules"])
        with ui.expansion("Веса итоговой оценки").classes("w-full"):
            self.numeric_tree(self.config["leaderboard"]["weights"])
            with ui.expansion("Веса ресурсов").classes("w-full"):
                self.numeric_tree(self.config["leaderboard"]["resource_weights"])
            ui.label("В каждой группе сумма весов должна равняться 1.").classes(
                "text-sm muted"
            )

    def operations(self):
        self.operations_box.clear()
        with self.operations_box:
            for pair, card in self.catalog.items():
                entry = next(
                    (
                        o
                        for o in self.config["operations"]
                        if (o["code"], o["version"]) == pair
                    ),
                    None,
                )
                with ui.expansion(
                    f"{card['title']} · v{card['version']}", value=entry is not None
                ).classes("w-full border rounded-lg"):

                    def enable(e, p=pair, c=card):
                        self.config["operations"] = [
                            o
                            for o in self.config["operations"]
                            if (o["code"], o["version"]) != p
                        ]
                        if e.value:
                            self.config["operations"].append(
                                {
                                    "code": p[0],
                                    "version": p[1],
                                    "visible_params": [
                                        v["param"] for v in c.get("visible_params", [])
                                    ]
                                    or c.get("default_visible_params", []),
                                }
                            )
                        self.on_change()
                        self.operations()

                    availability = ui.switch(
                        "Доступна в игре", value=entry is not None, on_change=enable
                    )
                    if self.config.get("schema_version") == 8:
                        availability.disable()
                    if entry is None:
                        continue
                    fields = (
                        {
                            "channel": {
                                "label": "Канал",
                                "kind": "select",
                                "default": card["channels"][0],
                                "options": [
                                    {"value": c, "label": self.labels.get(c, c)}
                                    for c in card["channels"]
                                ],
                            }
                        }
                        if card["channels"]
                        else {}
                    )
                    fields.update(
                        {f"context.{f['key']}": f for f in card["context_fields"]}
                    )
                    fields.update({f"action.{f['key']}": f for f in card["fields"]})

                    order = card.get("default_visible_params") or [
                        p["param"] for p in card.get("visible_params", [])
                    ]
                    fields = {key: fields[key] for key in order if key in fields}
                    if self.config.get("schema_version") == 8:
                        fields = {
                            key: value
                            for key, value in fields.items()
                            if not key.startswith("context.")
                            and key != "action.sender_relationship"
                        }
                    entry["visible_params"] = list(fields)
                    entry.pop("defaults", None)
                    # Rendering must not downgrade an expanded saved contract.
                    self.config.setdefault(
                        "schema_version", self.metadata["schema_version"]
                    )
                    ui.label("Все параметры доступны участнику").classes(
                        "text-xs muted"
                    )
                    with ui.row().classes("gap-2 w-full"):
                        for field in fields.values():
                            ui.label(field["label"]).classes(
                                "text-xs rounded-md bg-blue-50 text-blue-900 px-2 py-1"
                            )
                    if (
                        self.config.get("schema_version") == 8
                        and card["code"] == "purchase"
                    ):
                        ui.label(
                            "Покупка: 1 000–20 000 ₽, до трёх и 30 000 ₽ суммарно; комиссия 0, энергия 1, время 1. Параметры фиксированы."
                        )
                        continue
                    if self.config.get("schema_version") == 8:
                        for rule in self.metadata["overrides"]:
                            key = rule["key"]
                            if key == "risk_weight":
                                continue
                            value = entry.get(key)
                            if value is None:
                                value = card.get(
                                    key,
                                    card.get("costs", {}).get(
                                        key.removesuffix("_cost")
                                    ),
                                )
                            if value is not None:
                                ui.label(f"{rule['label']}: {value}").classes(
                                    "text-sm muted"
                                )
                        continue
                    with ui.expansion("Переопределить стоимость и лимиты").classes(
                        "w-full"
                    ):
                        for rule in self.metadata["overrides"]:
                            key = rule["key"]
                            with ui.row().classes("items-center w-full"):
                                toggle = ui.switch(
                                    rule["label"],
                                    value=key in entry and entry[key] is not None,
                                )
                                value_box = ui.row().classes("items-center")

                                def override(
                                    e,
                                    k=key,
                                    operation=entry,
                                    c=card,
                                    box=value_box,
                                    integer=rule["integer"],
                                ):
                                    if e.value:
                                        operation[k] = c.get(
                                            k,
                                            c.get("costs", {}).get(
                                                k.removesuffix("_cost"), 0
                                            ),
                                        )
                                    else:
                                        operation.pop(k, None)
                                    self.on_change()
                                    box.clear()
                                    if e.value:
                                        with box:
                                            self.text_number(
                                                operation, k, integer=integer
                                            )

                                toggle.on_value_change(override)
                                if key in entry and entry[key] is not None:
                                    with value_box:
                                        self.text_number(
                                            entry, key, integer=rule["integer"]
                                        )
