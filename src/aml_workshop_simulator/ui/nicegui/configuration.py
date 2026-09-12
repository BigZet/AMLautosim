"""Structured configuration form. No backend imports or local game files."""

from copy import deepcopy

from nicegui import ui


class ConfigForm:
    def __init__(self, config, catalog, metadata, on_change):
        self.config = deepcopy(config)
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
            .props("outlined dense inputmode=decimal")
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
        with ui.expansion("Карточки и параметры", value=True).classes("w-full"):
            self.operations_box = ui.column().classes("w-full")
            self.operations()
        with ui.expansion("Расчёт ресурсов").classes("w-full"):
            self.numeric_tree(self.config["resource_rules"])
        with ui.expansion("Скоринг").classes("w-full"):
            for field in ["review_threshold", "suspicious_threshold"]:
                self.text_number(self.config["scoring"], field)
            self.numeric_tree(self.config["scoring"]["rules"])
        with ui.expansion("Веса итоговой оценки").classes("w-full"):
            self.numeric_tree(self.config["leaderboard"]["weights"])
            with ui.expansion("Веса ресурсов").classes("w-full"):
                self.numeric_tree(self.config["leaderboard"]["resource_weights"])
            ui.label("В каждой группе сумма весов должна равняться 1.").classes(
                "text-sm muted"
            )
        with ui.expansion("Версии правил").classes("w-full"):
            for section in ("ruleset_version", "scoring", "leaderboard"):
                target, key = (
                    (self.config, section)
                    if section == "ruleset_version"
                    else (self.config[section], "version")
                )
                ui.select(
                    self.metadata["supported_versions"][section],
                    value=target[key],
                    label=section,
                    on_change=lambda e, t=target, k=key: (
                        t.__setitem__(k, e.value),
                        self.on_change(),
                    ),
                ).props("outlined dense")

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

                    ui.switch(
                        "Доступна в игре", value=entry is not None, on_change=enable
                    )
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
                    entry["visible_params"] = list(fields)
                    entry.pop("defaults", None)
                    self.config["schema_version"] = self.metadata["schema_version"]
                    ui.label("Все параметры доступны участнику").classes(
                        "text-xs muted"
                    )
                    with ui.row().classes("gap-2 w-full"):
                        for field in fields.values():
                            ui.label(field["label"]).classes(
                                "text-xs rounded-md bg-blue-50 text-blue-900 px-2 py-1"
                            )
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
