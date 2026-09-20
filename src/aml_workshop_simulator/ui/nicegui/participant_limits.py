"""Participant-facing rules from the published round, without scoring internals."""

from decimal import Decimal

from nicegui import ui

from src.aml_workshop_simulator.domain.channels import channel_label
from src.aml_workshop_simulator.domain.round_policy import CARD_OVERRIDE_KEYS


def number(value):
    return f"{Decimal(str(value)):,.2f}".rstrip("0").rstrip(".").replace(",", " ").replace(".", ",")


def money(value):
    return number(value) + " ₽"


def limits_view(config, cards):
    policies = {(p["code"], p.get("version", 1)): p for p in config["operations"]}
    active = []
    for card in cards:
        policy = policies.get((card["code"], card.get("version", 1)))
        if policy is not None:
            resolved = dict(card)
            if "costs" in card:
                resolved.update(energy_cost=card["costs"]["energy"], time_cost=card["costs"]["time"])
            active.append({**resolved, **{k: policy[k] for k in CARD_OVERRIDE_KEYS if policy.get(k) is not None}})
    titles = {c["code"]: c["title"] for c in active}
    constraints = config["constraints"]
    general = [
        ("Шагов в цепочке", f"До {config['objectives']['max_actions']}"),
        ("Одинаковых операций подряд", f"Не более {constraints['max_identical_steps']}"),
    ]
    for key, label in [("cash", "Наличные за раунд")]:
        if key in constraints["category_limits"]:
            general.append((label, "До " + money(constraints["category_limits"][key])))
    purchases = config.get("behavior", {}).get("purchases")
    if purchases and "purchase" in titles:
        general.append(("Покупки за раунд", "До " + money(purchases["max_total"])))
    operations = [
        {
            "id": c["code"], "name": c["title"],
            "amount": f"{number(c['min_amount'])}–{money(c['max_amount'])}",
            "count": c["max_occurrences"], "fee": number(Decimal(str(c["fee_rate"])) * 100) + "%",
            "energy": c["energy_cost"], "time": c["time_cost"],
        }
        for c in active
    ]
    dependencies = [f"«{c['title']}» — после «{titles.get(c['requires_card_code'], c['requires_card_code'])}»."
                    for c in active if c.get("requires_card_code")]
    additions = []
    costs = config.get("resource_rules", {})
    adjustment = costs.get("amount_adjustment", {})
    if adjustment.get("time_cost"):
        additions.append(("Сумма от " + money(adjustment["minimum_gross"]), f"+{adjustment['time_cost']} времени"))
    channels = {channel for card in active for channel in card.get("channels", [])}
    for channel, cost in costs.get("channel_time", {}).items():
        if cost and channel in channels:
            additions.append((channel_label(channel), f"+{cost} времени"))
    for card in active:
        for field in card.get("fields", []):
            for option in field.get("options", []):
                extra = [f"+{option[k]} {label}" for k, label in [("energy_cost", "энергии"), ("time_cost", "времени")] if option.get(k)]
                if extra:
                    additions.append((f"{card['title']} · {field['label']}: {option['label']}", ", ".join(extra)))
    timeline = config.get("behavior", {}).get("timeline")
    if timeline:
        for minutes, cost in sorted(timeline["waiting_costs"].items(), key=lambda item: int(item[0])):
            additions.append((f"Ожидание {minutes} мин", f"{cost} времени"))
    else:
        labels = {"rapid": "Быстрый темп", "normal": "Обычный темп", "spaced": "Операции с интервалом"}
        for key, value in costs.get("velocity_time", {}).items():
            additions.append((labels.get(key, key), f"+{value['time_cost']} времени"))
    return general, operations, dependencies, additions


def facts(rows):
    for label, value in rows:
        with ui.row().classes("rules-fact"):
            ui.label(label).classes("rules-fact-label")
            ui.label(str(value)).classes("rules-fact-value")


def participant_limits_panel(round_data, cards):
    config = round_data["game_config"]
    general, operations, dependencies, additions = limits_view(config, cards)
    short_names = {
        "salary": "Зарплата", "incoming_transfer": "Входящий перевод",
        "card_transfer": "Перевод по карте", "cash_withdrawal": "Наличные", "purchase": "Покупка",
    }
    operations = [{**row, "name": short_names.get(row["id"], row["name"])} for row in operations]
    short_labels = {"Шагов в цепочке": "Операций", "Одинаковых операций подряд": "Одинаковых подряд"}
    general = [(short_labels.get(label, label), value) for label, value in general]
    general[0] = ("Операций", f"1–{config['objectives']['max_actions']}")
    with ui.column().classes("profile-section rules-page"):
        ui.label("Ограничения раунда").classes("profile-section-title")
        with ui.element("div").classes("rules-columns"):
            with ui.column().classes("rules-section"):
                ui.label("Цель и ресурсы").classes("rules-heading")
                facts([("Цель", money(config["objectives"]["target_outflow"]))])
                facts([("Начальный баланс", money(config["resources"]["initial_balance"])),
                       ("Энергия / время", f"{config['resources']['initial_energy']} / {config['resources']['initial_time']}")])
            with ui.column().classes("rules-section"):
                ui.label("За раунд").classes("rules-heading")
                facts(general)
        with ui.column().classes("profile-subsection"):
            ui.label("Операции").classes("rules-heading")
            ui.table(columns=[{"name": key, "field": key, "label": label, "align": "left" if key == "name" else "right"} for key, label in [
                ("name", "Операция"), ("amount", "Сумма"), ("count", "Макс. за раунд"),
                ("fee", "Комиссия"), ("energy", "Энергия"), ("time", "Время"),
            ]], rows=operations, row_key="id", pagination={"rowsPerPage": 0}).props("flat dense wrap-cells hide-bottom").classes("w-full profile-history-table rules-operations-table")
            with ui.column().classes("rules-operations-mobile"):
                for operation in operations:
                    with ui.column().classes("rules-operation-mobile"):
                        ui.label(operation["name"]).classes("rules-heading")
                        facts([
                            ("Сумма", operation["amount"]),
                            ("Макс. операций / комиссия", f"{operation['count']} / {operation['fee']}"),
                            ("Энергия / время", f"{operation['energy']} / {operation['time']}"),
                        ])
            for text in dependencies:
                ui.label(text).classes("rules-note")
        with ui.column().classes("profile-subsection"):
            ui.label("Дополнительно к стоимости операции").classes("rules-heading")
            with ui.element("div").classes("rules-columns rules-costs"):
                with ui.column().classes("rules-section"):
                    facts([(label, value) for label, value in additions if not label.startswith("Ожидание ")])
                with ui.column().classes("rules-section"):
                    for label, value in additions:
                        if label.startswith("Ожидание "):
                            label = label.replace("1440 мин", "1 сутки").replace("60 мин", "1 час")
                            facts([(label, value)])
