"""Calendar time is distinct from the remaining game-time resource."""

from nicegui import ui


def timeline_control(timing, config, on_change):
    ui.label(
        f"Момент операции: {timing['occurred_at']} · {config['behavior']['timeline']['timezone']}"
    ).classes("text-xs muted")
    if timing["step_index"] == 1:
        ui.label("Начало сценария · ожидание 0").classes("text-xs muted")
    else:
        ui.select(
            {
                1: "1 минута · 0 времени",
                10: "10 минут · 1 времени",
                60: "1 час · 2 времени",
                1440: "1 сутки · 4 времени",
            },
            value=timing["interval_minutes"],
            label="Ожидание перед операцией",
            on_change=lambda event: on_change(event.value),
        ).props("outlined dense").classes("operation-parameter")


def timeline_summary(snapshot):
    timeline = snapshot.get("timeline")
    if not timeline:
        return
    ui.label(f"Календарное время · {timeline['timezone']}").classes(
        "text-sm font-semibold"
    )
    for step in timeline["steps"]:
        ui.label(
            f"Шаг {step['step_index']}: {step['occurred_at']} · "
            f"операция {step['operation_time_cost']} + ожидание {step['waiting_time_cost']} времени"
        ).classes("text-xs muted")
