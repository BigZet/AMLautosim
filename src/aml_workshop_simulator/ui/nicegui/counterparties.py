"""V8 party selectors and read-only details using the public snapshot."""

from nicegui import ui

from src.aml_workshop_simulator.domain.counterparty_roles import (
    PARTY_ROLES,
    party_allowed,
)

INFO = {
    "sufficient": "Сведения доступны",
    "limited": "Сведения ограничены",
    "unknown": "Сведения неизвестны",
}
CATEGORIES = {
    "employer": "Работодатель",
    "crypto_exchange": "Криптобиржа",
    "groceries": "Продукты",
    "clothing": "Одежда",
    "services": "Услуги",
}


def category_label(value):
    return CATEGORIES.get(value, value or "неизвестна")


KINDS = {
    "person": "Физическое лицо",
    "institution": "Организация",
    "merchant": "Торговая организация",
}


def expanded(config):
    return config.get("schema_version", 7) in (8, 9, 10)


def party_name(party):
    # Frozen catalogue titles once embedded a recipient role. The same identity
    # can send and receive; correct only these known legacy display strings.
    name = party["name"]
    if name in {
        "Получатель C — реквизиты различимы",
        "Получатель D — реквизиты различимы",
    }:
        return name.replace("Получатель ", "Контрагент ", 1)
    return name


def editable_params(card, config):
    if not expanded(config):
        return card["visible_params"]
    return [
        p
        for p in card["visible_params"]
        if (
            p["namespace"] == "channel"
            or p["namespace"] == "action"
            and p["key"] != "sender_relationship"
        )
    ]


def party_options(config, code, details=None):
    role, kinds = PARTY_ROLES.get(code, (None, ()))
    if config.get("schema_version") in (9, 10):
        from src.aml_workshop_simulator.services.semantic_contract import allowed_party

        return role, {
            p["id"]: party_name(p)
            for p in config["behavior"]["counterparties"]
            if allowed_party(code, p, details or {})
        }
    return role, {
        p["id"]: party_name(p)
        for p in config["behavior"]["counterparties"]
        if party_allowed(code, p, config["behavior"].get("sender_policy"))
    }


def party_description(config, identity):
    party = next(
        (p for p in config["behavior"]["counterparties"] if p["id"] == identity), None
    )
    if party is None:
        return "Выберите сторону из каталога раунда"
    operations = config["behavior"]["history"]["operations"]
    history = (
        "История недоступна"
        if operations is None
        else (
            f"Операций в предыстории: {sum(op.get('counterparty_id') == identity for op in operations)}"
        )
    )
    return " · ".join(
        [
            party_name(party),
            KINDS[party["kind"]],
            INFO[party["information_status"]],
            (
                "Личное знакомство есть"
                if party["personal_relationship"] == "known"
                else "Личное знакомство неизвестно"
            )
            if party["kind"] == "person"
            else "Роль: "
            + CATEGORIES.get(
                party.get("category"), party.get("category") or "Организация"
            ),
            history,
            *(
                ["Категория: " + category_label(party.get("category"))]
                if party["kind"] == "merchant"
                else []
            ),
        ]
    )


def party_selector(config, step, on_change):
    role, options = party_options(
        config, step["card"]["code"], step.get("action_details")
    )
    if role is None:
        return
    label = "Отправитель" if role == "sender_id" else "Получатель"
    if len(options) == 1:
        identity = next(iter(options))
        if step.get(role) != identity:
            on_change(role, identity)
        ui.label(f"{label}: {options[identity]}").classes("text-sm muted")
        return
    details = ui.label(party_description(config, step.get(role))).classes(
        "text-xs muted"
    )

    def update(event):
        on_change(role, event.value)
        details.set_text(party_description(config, event.value))

    ui.select(options, value=step.get(role), label=label, on_change=update).props(
        "outlined dense options-dense"
    ).classes("operation-parameter")


def party_readonly(config, step):
    for role, label in (("sender_id", "Отправитель"), ("recipient_id", "Получатель")):
        if step.get(role):
            ui.label(f"{label}: {party_description(config, step[role])}").classes(
                "text-sm muted"
            )


def catalog_form(behavior, on_change):
    """Shared catalogue edited only in a draft, IDs stable across references."""
    from uuid import uuid4

    with ui.expansion("Каталог сторон").classes("w-full"):
        box = ui.column().classes("w-full")

        def render():
            box.clear()
            with box:
                for party in behavior["counterparties"]:
                    with ui.card().classes("w-full"):

                        def set_value(key, value, p=party):
                            p[key] = value
                            on_change()

                        ui.input(
                            "Название стороны",
                            value=party["name"],
                            on_change=lambda e, setter=set_value: setter(
                                "name", e.value
                            ),
                        )
                        for key, label, options in [
                            ("kind", "Тип стороны", KINDS),
                            ("information_status", "Доступные сведения", INFO),
                            (
                                "personal_relationship",
                                "Личное знакомство",
                                {"known": "Есть", "unknown": "Неизвестно"},
                            ),
                        ]:
                            selector = ui.select(
                                options,
                                label=label,
                                value=party[key],
                                on_change=lambda e, k=key, setter=set_value: setter(
                                    k, e.value
                                ),
                            )
                            if key == "kind":
                                kind_selector = selector
                        ui.input(
                            "Категория организации",
                            value=CATEGORIES.get(
                                party.get("category"), party.get("category") or ""
                            ),
                            on_change=lambda e, setter=set_value: setter(
                                "category",
                                {v: k for k, v in CATEGORIES.items()}.get(
                                    e.value, e.value
                                )
                                or None,
                            ),
                        ).bind_visibility_from(
                            kind_selector,
                            "value",
                            backward=lambda kind: kind != "person",
                        )

                def add():
                    behavior["counterparties"].append(
                        {
                            "id": str(uuid4()),
                            "name": "Новая сторона",
                            "kind": "person",
                            "information_status": "unknown",
                            "personal_relationship": "unknown",
                            "category": None,
                        }
                    )
                    on_change()
                    render()

                ui.button("Добавить сторону", on_click=add)

        render()
