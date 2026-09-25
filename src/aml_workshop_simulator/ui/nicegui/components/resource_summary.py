"""Participant resource summary presentation, independent of editor ownership."""

from decimal import Decimal
from datetime import datetime
from nicegui import ui


def display_number(value):
    return f"{Decimal(str(value)):,f}".replace(",", " ").replace(".", ",")


def display_operation_amount(value):
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    return display_number(
        amount.quantize(Decimal("1"))
        if amount == amount.to_integral_value()
        else amount
    )


def display_moment(value):
    return datetime.fromisoformat(value).strftime("%d.%m.%Y, %H:%M")


def credited_outflow(snapshot):
    totals = snapshot["totals"]
    return totals.get("target_outflow", totals["gross_outflow"])


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
                    "resource-amount"
                    + (
                        " resource-negative"
                        if Decimal(str(values["balance"])) < 0
                        else ""
                    )
                )
                ui.label("₽").classes("resource-currency")
        with ui.column().classes("resource-meters"):
            for key, label in [("energy", "Энергия"), ("time", "Время")]:
                remaining = Decimal(str(values[key]))
                capacity = Decimal(str(initial.get(f"initial_{key}", 0)))
                fraction = (
                    float(max(Decimal(0), min(Decimal(1), remaining / capacity)))
                    if capacity > 0
                    else 0
                )
                with ui.column().classes("resource-meter"):
                    with ui.row().classes("resource-meter-heading"):
                        ui.label(label).classes("resource-caption")
                        ui.label(display_number(values[key])).classes(
                            "resource-meter-value"
                            + (" resource-negative" if remaining < 0 else "")
                        )
                    ui.linear_progress(
                        value=fraction, show_value=False, size="3px"
                    ).classes("resource-meter-bar").props(
                        f'aria-label="{label}: {display_number(values[key])}"'
                    )


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
                    "font-semibold text-lg"
                    + (" resource-negative" if Decimal(str(values[key])) < 0 else "")
                )
