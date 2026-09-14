"""Render only the explanation saved with the participant's scored result."""

from nicegui import ui


def number(value, digits=6, signed=False):
    return format(value, ("+" if signed else "") + f".{digits}f").replace(".", ",")


def shap_result(explanation, *, expanded=False, on_change=None):
    factors = {f["code"]: f for f in explanation["factors"]}
    with ui.card().classes("panel w-full min-w-0"):
        ui.label("Почему модель поставила такую оценку").classes(
            "text-lg font-semibold"
        )
        ui.label(explanation["disclaimer"]).classes("text-sm muted")
        for title, key in [
            ("Повысило оценку", "top_positive"),
            ("Снизило оценку", "top_negative"),
        ]:
            ui.label(title).classes("font-semibold mt-3")
            if not explanation[key]:
                ui.label("Заметных вкладов этого знака нет.").classes("text-sm muted")
            for code in explanation[key]:
                factor_row(factors[code])
        ui.label(
            f"Остальные вклады: {number(explanation['remaining_contribution'], 4, True)} балла"
        ).classes("text-sm")
        with ui.expansion(
            "Подробный расчёт", value=expanded, on_value_change=on_change
        ).classes("w-full min-w-0"):
            ui.label(f"Базовое значение модели: {number(explanation['base_value'])}")
            ui.label(
                "База соответствует обучающим данным модели; это не нулевой риск."
            ).classes("text-sm muted")
            for factor in sorted(
                factors.values(), key=lambda f: (-abs(f["contribution"]), f["code"])
            ):
                factor_row(factor, detailed=True)
            for title, key in [
                ("Исходный прогноз", "raw_score"),
                ("Ограничение диапазоном 0–100", "clipping_adjustment"),
                ("Поправка округления", "rounding_adjustment"),
            ]:
                ui.label(f"{title}: {number(explanation[key])}")
            ui.label(
                f"Итоговый риск: {str(explanation['normalized_score']).replace('.', ',')} / 100"
            ).classes("font-semibold")
            ui.label(
                "Вклады связаны между собой. Изменение отдельной операции не обязано менять риск на показанную величину."
            ).classes("text-sm muted")


def factor_row(factor, detailed=False):
    with ui.column().classes("w-full min-w-0 gap-1 py-2"):
        with ui.row().classes("w-full justify-between items-start gap-2"):
            ui.label(factor["title"]).classes("break-words flex-1 min-w-0")
            ui.label(
                number(factor["contribution"], 6, True)
                if detailed
                else f"{number(factor['contribution'], 2, True)} балла"
            ).classes("font-semibold")
        ui.label(
            f"Значение: {str(factor['display_value']).replace('.', ',')} {factor['unit']}"
        ).classes("text-sm")
        if detailed:
            ui.label(factor["description"]).classes("text-sm muted break-words")
