"""Render only the explanation saved with the participant's scored result."""

import math

from nicegui import ui

from src.aml_workshop_simulator.schemas.scoring import (
    AMLProbabilityExplanationOut,
    GamePatternExplanationOut,
)


def number(value, digits=6, signed=False):
    return format(value, ("+" if signed else "") + f".{digits}f").replace(".", ",")


def shap_result(explanation, *, expanded=False, on_change=None):
    if explanation.get("schema_version") == 5:
        game_pattern_result(explanation, expanded=expanded, on_change=on_change)
        return
    if explanation.get("schema_version") == 4:
        aml_probability_result(explanation, expanded=expanded, on_change=on_change)
        return
    if explanation.get("schema_version") != 3:
        raise ValueError("Unsupported scoring explanation version")
    factors = {f["code"]: f for f in explanation["factors"]}
    with ui.card().classes("panel w-full min-w-0"):
        ui.label("Почему модель поставила такую оценку").classes(
            "text-lg font-semibold"
        )
        ui.label(explanation["disclaimer"]).classes("text-sm muted")
        for title, key in [
            ("Повысило риск", "top_positive"),
            ("Снизило риск", "top_negative"),
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
        value = factor["display_value"]
        if factor["code"] == "income_basis" and factor.get("value") == "absent":
            value = "В текущей цепочке нет получения дохода"
        ui.label(f"Значение: {str(value).replace('.', ',')} {factor['unit']}").classes(
            "text-sm"
        )
        if not detailed:
            ui.linear_progress(
                value=min(abs(factor["contribution"]) / 100, 1),
                show_value=False,
                color="orange" if factor["contribution"] > 0 else "teal",
            ).props("rounded").classes("w-full")
        if detailed:
            ui.label(factor["description"]).classes("text-sm muted break-words")


def aml_probability_display(p, category, score_kind="aml_probability"):
    """Shared probability/category formatting for results and both leaderboards."""
    if type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1:
        raise ValueError("Invalid AML probability")
    expected = "low" if p < 0.1 else "high" if p >= 0.9 else "review"
    if category != expected:
        raise ValueError("Category differs from unrounded probability")
    percentage = (
        "<0,1%" if p < 0.001 else ">99,9%" if p > 0.999 else f"{number(100 * p, 1)}%"
    )
    labels = {
        "low": "Низкая вероятность",
        "review": "Требует проверки",
        "high": "Высокая вероятность",
    }
    if score_kind == "educational_pattern_probability":
        labels = {
            "low": "Низкое соответствие",
            "review": "Пограничная цепочка",
            "high": "Высокое соответствие",
        }
    return {
        "title": "Соответствие учебным AML-паттернам"
        if score_kind == "educational_pattern_probability"
        else "Вероятность AML-сценария в учебной модели",
        "probability_text": percentage,
        "category": category,
        "category_title": labels[category],
    }


def aml_result_view_model(explanation):
    """Validate a saved result and format it without invoking any scorer."""
    if explanation.get("schema_version") == 5:
        result = GamePatternExplanationOut.model_validate(explanation)
        return {
            **aml_probability_display(
                result.aml_probability, result.category, result.score_kind
            ),
            "score_kind": result.score_kind,
            "context_status": "complete",
            "context_text": "Общая история и игровые ограничения одинаковы для всех участников.",
            "explanation": result.model_dump(),
        }
    result = AMLProbabilityExplanationOut.model_validate(explanation)
    return {
        **aml_probability_display(result.aml_probability, result.category),
        "score_kind": result.score_kind,
        "context_status": result.context_status,
        "context_text": (
            "Контекст: полный"
            if result.context_status == "complete"
            else "Контекст: частичный — часть сведений отсутствует"
        ),
        "explanation": result.model_dump(),
    }


def aml_probability_result(explanation, *, expanded=False, on_change=None):
    view = aml_result_view_model(explanation)
    result = view["explanation"]
    factors = sorted(
        result["shap_values"], key=lambda f: (-abs(f["contribution"]), f["feature"])
    )
    with ui.card().classes("panel w-full min-w-0"):
        ui.label(view["title"]).classes("text-lg font-semibold")
        ui.label(view["probability_text"]).classes("text-2xl font-semibold")
        ui.label(view["category_title"]).classes("font-semibold")
        ui.label(view["context_text"]).classes("text-sm")
        ui.label(
            "Полнота контекста описывает наличие сведений, а не уверенность модели. "
            "Вероятность относится к учебной популяции, а не к банковской статистике."
        ).classes("text-sm muted")
        ui.label(
            "SHAP показывает связь признаков с прогнозом: это не доказательство AML "
            "и не причинный эффект. Вклады выражены в raw margin, не в процентах."
        ).classes("text-sm muted")
        for title, sign in [
            ("Повысило прогноз модели", 1),
            ("Снизило прогноз модели", -1),
        ]:
            ui.label(title).classes("font-semibold mt-3")
            selected = [
                factor for factor in factors if factor["contribution"] * sign > 0
            ][:3]
            if not selected:
                ui.label("Заметных вкладов этого знака нет.").classes("text-sm muted")
            for factor in selected:
                aml_factor_row(factor)
        with ui.expansion(
            "Подробный расчёт", value=expanded, on_value_change=on_change
        ).classes("w-full min-w-0"):
            ui.label(f"Базовое значение (raw margin): {number(result['base_margin'])}")
            for factor in factors:
                aml_factor_row(factor)
            ui.label(
                f"База + все вклады = исходный raw margin: {number(result['raw_margin'])}"
            )
            ui.label(f"Погрешность суммы SHAP: {number(result['shap_residual'], 8)}")
            ui.label(
                "Калибратор применяется отдельно к суммарному raw margin. "
                "Процентные вклады отдельных признаков не складываются."
            ).classes("text-sm muted")
            ui.label(
                f"Метод калибровки: {result['calibration']['parameters']['method']}"
            )


def game_pattern_result(explanation, *, expanded=False, on_change=None):
    view = aml_result_view_model(explanation)
    result = view["explanation"]
    with ui.card().classes("panel w-full min-w-0"):
        ui.label(view["title"]).classes("text-lg font-semibold")
        ui.label(f"{number(result['risk_score'], 2)} / 100").classes(
            "text-2xl font-semibold"
        )
        ui.label(view["category_title"])
        ui.label(view["context_text"]).classes("text-sm muted")
        ui.label(
            "Оценка описывает учебный паттерн, а не доказанную преступность. Меньший скор улучшает результат при соблюдении игровых ограничений."
        ).classes("text-sm muted")
        for window in result["windows"]:
            with ui.expansion(
                f"Окно {window['minutes']} мин: {number(100 * window['probability'], 2)}%",
                value=expanded,
            ).classes("w-full"):
                ui.label(
                    "Вклады SHAP относятся к логиту этого окна; они не складываются в проценты итогового скора."
                ).classes("text-sm muted")
                for factor in sorted(
                    window["shap_values"], key=lambda f: -abs(f["contribution"])
                ):
                    aml_factor_row(factor)
                ui.label(
                    f"База {number(window['base_margin'])} + вклады = {number(window['raw_margin'])}; погрешность {number(window['shap_residual'], 8)}"
                )
        with ui.expansion(
            "Как получен итоговый скор", value=expanded, on_value_change=on_change
        ).classes("w-full"):
            ui.label(
                f"Средняя вероятность трёх окон: {number(result['uncalibrated_probability'])}"
            )
            ui.label(
                f"Калибровка: {result['calibration']['parameters']['method']}; применяется к логиту средней вероятности."
            )
            ui.label(
                f"Итог: 100 × {number(result['aml_probability'])} = {number(result['risk_score'], 2)}"
            )


def aml_factor_row(factor):
    with ui.column().classes("w-full min-w-0 gap-1 py-2"):
        with ui.row().classes("w-full justify-between items-start gap-2"):
            ui.label(factor["title"]).classes("break-words flex-1 min-w-0")
            ui.label(f"{number(factor['contribution'], 6, True)} raw margin").classes(
                "font-semibold"
            )
        value = (
            number(factor["value"])
            if isinstance(factor["value"], (float, int))
            else factor["value"]
        )
        ui.label(f"Значение: {value}").classes("text-sm")
        ui.label(factor["description"]).classes("text-sm muted break-words")
