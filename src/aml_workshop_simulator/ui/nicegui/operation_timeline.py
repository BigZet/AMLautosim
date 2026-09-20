"""Calendar time is distinct from the remaining game-time resource."""

from nicegui import ui
from datetime import datetime


def moment(value):
    return datetime.fromisoformat(value).strftime("%d.%m.%Y, %H:%M")


def timeline_control(timing, config, on_change):
    if timing["step_index"] == 1:
        return
    ui.select(
        {1: "1 минута", 10: "10 минут", 60: "1 час", 1440: "1 сутки"},
        value=timing["interval_minutes"],
        label="Ожидание перед операцией",
        on_change=lambda event: on_change(event.value),
    ).props("outlined dense hide-bottom-space").classes("operation-parameter")


def timeline_summary(snapshot):
    timeline = snapshot.get("timeline")
    if not timeline:
        return
    ui.label(f"Календарное время · {timeline['timezone']}").classes(
        "text-sm font-semibold"
    )
    for step in timeline["steps"]:
        ui.label(
            f"Шаг {step['step_index']}: {moment(step['occurred_at'])} · "
            f"операция {step['operation_time_cost']} + ожидание {step['waiting_time_cost']} времени"
        ).classes("text-xs muted")
